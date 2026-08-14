"""Server-rendered pilot order operations panel.

This router exposes the human-readable inspection surface for the
pilot operator under ``/admin/pilot/orders``. It is strictly
read-only and does not mutate any Pedido, Session, Cliente, provider
receipt or outbound row. It does not commit, rollback, flush, refresh,
begin or close the database session; the request-level dependency
remains the transaction owner.

The panel uses an HTTP Basic challenge whose password validates
against the existing configured administrative token with a
constant-time comparison. The username is ignored. The existing
``X-Admin-Token`` contract for the JSON API is unchanged.

The bounded local-test ``POST /admin/pilot/orders/{pedido_id}/local-test``
route is the single state-changing route family. It re-validates the
exact selected Pedido and its Session, invokes the existing
transactional message processor and returns the mapped customer
responses to the browser-only transcript. It does not call the
generic HTTP incoming-message endpoint, the provider coordinator,
Twilio or the worker; it never creates a provider receipt, a
deferred processing record, an outbound row, a worker lease or a
Twilio request.

After a successful turn the route re-validates the exact same
Pedido and Session and projects a closed, typed snapshot of the new
execution state for the browser-side state cells. The router never
serializes the raw Session, Pedido, ``pending_intents`` JSON,
source text, resolved values, candidate identifiers, queue
payloads, diagnostics, exceptions, environment variables, settings,
tokens or provider data. The transactional message processor
remains the only commit/rollback authority; the route never calls
``commit``, ``rollback``, ``flush``, ``refresh``, ``begin``, ``close``
or ``expire``.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path as PathLib
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.dependencies import get_session, require_admin_pilot_basic
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.models import (
    EstadoPedido,
    EstadoSession,
    Pedido,
)
from backend.models import (
    Session as SessionModel,
)
from backend.services.pilot_order_operations_view_service import (
    ALLOWED_PAGE_SIZES,
    InvalidComercioId,
    InvalidListFilter,
    InvalidPedidoId,
    ListFilters,
    OrderLineSnapshot,
    PendingContextDebugView,
    PilotOrderOperationsViewService,
    build_pending_context_debug_view,
    parse_comercio_id,
    parse_list_filters,
    parse_pedido_id,
)

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1] / "templates" / "admin_pilot_orders"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

_ESTADO_VALUES: tuple[str, ...] = tuple(member.value for member in EstadoPedido)

LOCAL_TEST_MAX_MESSAGE_CHARS = 500
LOCAL_TEST_ORIGIN_HEADER = "X-Local-Test-Origin"
LOCAL_TEST_ORIGIN_VALUE = "same-origin"
LOCAL_TEST_REJECTED_MESSAGE = (
    "El canal local rechazó el mensaje. Revisá la consola y el "
    "panel principal para más detalles."
)
LOCAL_TEST_EXECUTION_STATE_EMPTY_SCHEMA_VERSION = ""


def _service(
    session: Annotated[Session, Depends(get_session)],
) -> PilotOrderOperationsViewService:
    return PilotOrderOperationsViewService(session)


router = APIRouter(
    prefix="/admin/pilot/orders",
    tags=["admin-pilot-orders"],
    dependencies=[Depends(require_admin_pilot_basic)],
)


def _render(
    request: Request,
    template_name: str,
    context: dict[str, object],
) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=200,
    )


def _build_list_url(
    *,
    base: str,
    params: dict[str, object],
) -> str:
    encoded = urlencode(
        [(key, value) for key, value in params.items() if value not in (None, "")],
        doseq=False,
    )
    if not encoded:
        return base
    return f"{base}?{encoded}"


def _reject_local_test(reason: str) -> JSONResponse:
    """Return the documented generic rejection payload.

    The route never emits a precise diagnostic so the response
    cannot be used to enumerate the operator error class. It is the
    only JSON body the route emits for invalid submissions.
    """
    return JSONResponse(
        status_code=400,
        content={
            "responses": [],
            "message": LOCAL_TEST_REJECTED_MESSAGE,
        },
    )


def _load_local_test_session(
    db: Session,
    pedido_id: int,
) -> tuple[Pedido, SessionModel] | None:
    """Load the exact Pedido and Session for the local-test route.

    Returns ``(pedido, session)`` when the exact positive pedido id
    exists, the linked Session exists, ``session.id_pedido`` equals
    the pedido id, the Session is active and the related
    cliente/comercio/pedido foreign keys are internally consistent.
    Returns ``None`` for every other shape so the caller can emit the
    documented generic rejection without leaking which invariant
    failed. The loader never searches for another session and never
    returns a foreign session.

    The pre-turn eligibility contract — ``pedido.estado_pedido ==
    BORRADOR`` — applies only here. The post-turn snapshot loader
    (:func:`_reload_exact_session_for_snapshot`) must NOT re-check
    it: a successful business turn may legitimately leave the
    pedido in ``ingresado`` and the panel must still surface the
    refreshed execution state.
    """
    stmt = (
        select(Pedido)
        .where(Pedido.id == pedido_id)
        .options(
            joinedload(Pedido.session).joinedload(SessionModel.cliente),
            joinedload(Pedido.session).joinedload(SessionModel.comercio),
        )
    )
    pedido = db.execute(stmt).unique().scalar_one_or_none()
    if pedido is None:
        return None
    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return None
    session = getattr(pedido, "session", None)
    if session is None:
        return None
    if session.id_pedido != pedido.id:
        return None
    if session.estado_session != EstadoSession.ACTIVA:
        return None
    if session.id_comercio != pedido.session.comercio.id:
        return None
    if session.id_cliente != pedido.session.cliente.id:
        return None
    return pedido, session


def _reload_exact_session_for_snapshot(
    db: Session,
    pedido_id: int,
    session_id: int,
) -> tuple[Pedido, SessionModel] | None:
    """Re-load the exact Pedido and Session to project the closed
    execution-state snapshot after a successful business turn.

    The helper is deliberately narrower than
    :func:`_load_local_test_session`: it does NOT re-check
    ``pedido.estado_pedido == BORRADOR``, because a valid
    confirm-order turn legitimately flips the pedido to
    ``ingresado``. It does NOT validate comercio/cliente FK
    consistency either: those invariants were already enforced by
    the pre-turn loader and the processor mutates only its own
    exact target.

    Identity is enforced by exact ``pedido.id`` AND
    ``session.id_pedido == pedido.id`` AND
    ``session.id == session_id``. If any of those links is broken
    — for example the session was deleted or got re-pointed to a
    different pedido during the turn — the helper returns
    ``None`` so the caller can emit the documented generic
    rejection without leaking which invariant failed.

    The helper MUST NOT search for a successor session, another
    active session for the same cliente/comercio, or any fallback
    target. If the exact identity is gone, the request fails closed.
    """
    stmt = (
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .where(SessionModel.id_pedido == pedido_id)
        .options(
            joinedload(SessionModel.pedido),
            joinedload(SessionModel.cliente),
            joinedload(SessionModel.comercio),
        )
    )
    session = db.execute(stmt).unique().scalar_one_or_none()
    if session is None:
        return None
    pedido = getattr(session, "pedido", None)
    if pedido is None:
        return None
    if pedido.id != pedido_id:
        return None
    return pedido, session


class LocalTestRequest(BaseModel):
    """Bounded request schema for the panel-local test route.

    The schema mirrors the IncomingMessageRequest shape but adds a
    maximum message length so the form cannot be used to push
    arbitrarily large payloads through the panel. ``extra='forbid'``
    keeps the request surface minimal.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=LOCAL_TEST_MAX_MESSAGE_CHARS)


class LocalTestExecutionState(BaseModel):
    """Closed, typed execution-state snapshot for the exact selected
    Session.

    The schema mirrors the documented fields of
    :class:`PendingContextDebugView` so the browser can replace each
    existing state cell with ``textContent`` without ever receiving
    raw JSON, source text, resolved values, candidate identifiers,
    queue payloads, diagnostics, exception detail, environment,
    settings, tokens, secrets or provider data. ``schema_version``
    is emitted as ``null`` when the version is unknown; the
    browser uses an em dash placeholder for that case.
    """

    model_config = ConfigDict(extra="forbid")

    context_type: str
    pending_encoding: str
    active_intent: str
    active_status: str
    candidate_count: int
    requirements_pending_count: int
    requirements_completed_count: int
    queue_length: int
    schema_version: int | None
    consistency: str


class LocalTestOrderLine(BaseModel):
    """JSON-safe typed order-line snapshot for the exact selected
    Pedido.

    The schema mirrors :class:`OrderLineSnapshot` and is built from
    the documented closed fields only. ``precio_unitario_display``
    is a pre-formatted display string (built from the stored
    :class:`decimal.Decimal` value through
    :func:`format_order_line_price`) so the response is JSON-safe
    without exposing a raw ``Decimal``. ``extra='forbid'`` rejects
    any future regression that tries to leak ORM, Session, Pedido,
    pending, provider, diagnostic or credential data.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    producto_nombre: str
    presentacion_descripcion: str | None
    cantidad: int
    precio_unitario_display: str
    observaciones: str | None


class LocalTestResponse(BaseModel):
    """Successful local-test response payload.

    The payload is built explicitly so the route cannot accidentally
    serialize the raw Session, Pedido or ``pending_intents``.
    ``responses`` carries the mapped customer turns; ``execution_state``
    carries the closed snapshot for the existing state cells;
    ``order_lines`` carries the typed, JSON-safe line snapshot for
    the exact selected Pedido so the browser can refresh the
    centre-column lines list in place. The schema rejects any
    extra member so a future regression that starts leaking raw
    fields would fail at runtime.
    """

    model_config = ConfigDict(extra="forbid")

    responses: list[dict[str, str]]
    execution_state: LocalTestExecutionState
    order_lines: list[LocalTestOrderLine]


def _serialize_execution_state(
    view: PendingContextDebugView,
) -> LocalTestExecutionState:
    """Build a :class:`LocalTestExecutionState` from a pending-context
    debug view.

    The helper pulls only the documented closed fields via
    :func:`dataclasses.asdict` so a future field added to the
    underlying dataclass never leaks into the wire payload. It must
    be called with the freshest projection for the exact selected
    Session so the operator sees the updated state after a
    successful turn. The serializer never inspects the database or
    the configuration.
    """
    payload = asdict(view)
    return LocalTestExecutionState(
        context_type=payload["context_type"],
        pending_encoding=payload["pending_encoding"],
        active_intent=payload["active_intent"],
        active_status=payload["active_status"],
        candidate_count=int(payload["candidate_count"]),
        requirements_pending_count=int(payload["requirements_pending_count"]),
        requirements_completed_count=int(
            payload["requirements_completed_count"]
        ),
        queue_length=int(payload["queue_length"]),
        schema_version=(
            int(payload["schema_version"])
            if payload["schema_version"] is not None
            else None
        ),
        consistency=payload["consistency"],
    )


@router.get("", response_class=HTMLResponse)
def list_orders(
    request: Request,
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
    raw_from: Annotated[str | None, Query(alias="from")] = None,
    raw_to: Annotated[str | None, Query(alias="to")] = None,
    raw_comercio_id: Annotated[str | None, Query(alias="comercio_id")] = None,
    raw_estado: Annotated[str | None, Query(alias="estado")] = None,
    raw_page: Annotated[str | None, Query(alias="page")] = None,
    raw_page_size: Annotated[str | None, Query(alias="page_size")] = None,
) -> Response:
    try:
        filters: ListFilters = parse_list_filters(
            raw_from=raw_from,
            raw_to=raw_to,
            raw_comercio_id=raw_comercio_id,
            raw_estado=raw_estado,
            raw_page=raw_page,
            raw_page_size=raw_page_size,
        )
    except InvalidListFilter as exc:
        return _templates.TemplateResponse(
            request=request,
            name="bad_request.html",
            context={"message": str(exc)},
            status_code=400,
        )

    list_view = service.list_orders(filters)
    total_pages = (
        (list_view.total + list_view.page_size - 1) // list_view.page_size
        if list_view.total > 0
        else 0
    )

    def paginator_url(page: int) -> str:
        params = {
            "from": filters.from_date.isoformat(),
            "to": filters.to_date.isoformat(),
            "comercio_id": filters.comercio_id,
            "estado": filters.estado.value if filters.estado else None,
            "page_size": filters.page_size,
            "page": page,
        }
        return _build_list_url(
            base="/admin/pilot/orders",
            params=params,
        )

    return _render(
        request,
        "list.html",
        {
            "filters": filters,
            "list_view": list_view,
            "total_pages": total_pages,
            "estado_choices": _ESTADO_VALUES,
            "page_size_choices": ALLOWED_PAGE_SIZES,
            "paginator_url": paginator_url,
        },
    )


@router.get("/{pedido_id}", response_class=HTMLResponse)
def detail_order(
    request: Request,
    pedido_id: Annotated[str, Path()],
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
) -> Response:
    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": pedido_id},
            status_code=404,
        )

    detail = service.get_detail(parsed_id)
    if detail is None:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": pedido_id},
            status_code=404,
        )

    history = service.get_provider_history(
        cliente_id=detail.client.id,
        comercio_id=detail.commerce.id,
        zona_horaria=detail.commerce.zona_horaria,
    )

    return _render(
        request,
        "detail.html",
        {
            "detail": detail,
            "history": history,
            "local_test_max_chars": LOCAL_TEST_MAX_MESSAGE_CHARS,
        },
    )


@router.post("/{pedido_id}/local-test", response_class=JSONResponse)
def local_test_message(
    pedido_id: Annotated[str, Path()],
    payload: LocalTestRequest,
    db: Annotated[Session, Depends(get_session)],
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
    origin_header: Annotated[
        str | None, Header(alias=LOCAL_TEST_ORIGIN_HEADER)
    ] = None,
) -> JSONResponse:
    """Panel-local test channel for the exact selected Pedido.

    This is the only state-changing route in the panel. It re-loads
    the exact Pedido and Session, validates every documented
    invariant, and then invokes the existing transactional message
    processor for the exact Session. It never falls back to another
    session for the same cliente/comercio and never creates provider
    receipts, deferred records, outbound rows, worker leases or
    Twilio deliveries.

    After the processor returns, the route re-loads the exact same
    Pedido/Session identity — without re-applying the
    ``borrador``-only eligibility contract — and projects a typed,
    closed snapshot of the new execution state for the browser-side
    state cells. A successful turn that legitimately moves the
    pedido from ``borrador`` to ``ingresado`` MUST still return the
    mapped responses and the refreshed snapshot; the route never
    substitutes a successor session or another active session. The
    route does not serialize the raw Session, Pedido,
    ``pending_intents`` JSON, source text, resolved values,
    candidate identifiers, queue payloads, diagnostics, exception
    detail, environment, settings, tokens or provider data. The
    transactional message processor remains the only
    commit/rollback authority; the route never calls ``commit``,
    ``rollback``, ``flush``, ``refresh``, ``begin``, ``close`` or
    ``expire``.
    """
    if origin_header != LOCAL_TEST_ORIGIN_VALUE:
        return _reject_local_test("missing same-origin header")

    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        return _reject_local_test("invalid pedido id")

    loaded = _load_local_test_session(db, parsed_id)
    if loaded is None:
        return _reject_local_test("target not eligible")
    _, exact_session = loaded

    responses = process_incoming_message_with_responses(
        db, exact_session, payload.message
    )

    refreshed = _reload_exact_session_for_snapshot(
        db, parsed_id, exact_session.id
    )
    if refreshed is None:
        return _reject_local_test("target identity no longer present")
    _, refreshed_session = refreshed

    execution_state = build_pending_context_debug_view(
        raw_context_type=refreshed_session.context_type,
        raw_pending_intents=refreshed_session.pending_intents,
    )

    order_lines_snapshot: list[OrderLineSnapshot] = service.get_order_lines_snapshot(
        parsed_id
    )

    response_payload = LocalTestResponse(
        responses=[
            {
                "message": response.message,
                "intent": response.intent,
                "status": response.status,
            }
            for response in responses
        ],
        execution_state=_serialize_execution_state(execution_state),
        order_lines=[
            LocalTestOrderLine(
                id=snapshot.id,
                producto_nombre=snapshot.producto_nombre,
                presentacion_descripcion=snapshot.presentacion_descripcion,
                cantidad=snapshot.cantidad,
                precio_unitario_display=snapshot.precio_unitario_display,
                observaciones=snapshot.observaciones,
            )
            for snapshot in order_lines_snapshot
        ],
    )
    return JSONResponse(
        status_code=200,
        content=response_payload.model_dump(),
    )


@router.get("/commerce/{comercio_id}/catalog", response_class=HTMLResponse)
def commerce_catalog(
    request: Request,
    comercio_id: Annotated[str, Path()],
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
) -> Response:
    try:
        parsed_comercio_id = parse_comercio_id(comercio_id)
    except InvalidComercioId:
        return _templates.TemplateResponse(
            request=request,
            name="bad_request.html",
            context={"message": "comercio_id must be a positive integer"},
            status_code=400,
        )

    catalog_view = service.get_commerce_catalog_price_availability(
        parsed_comercio_id
    )
    if catalog_view is None:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": comercio_id},
            status_code=404,
        )

    return _render(
        request,
        "catalog.html",
        {"catalog_view": catalog_view},
    )


__all__ = [
    "LOCAL_TEST_EXECUTION_STATE_EMPTY_SCHEMA_VERSION",
    "LOCAL_TEST_MAX_MESSAGE_CHARS",
    "LOCAL_TEST_ORIGIN_HEADER",
    "LOCAL_TEST_ORIGIN_VALUE",
    "_ESTADO_VALUES",
    "LocalTestExecutionState",
    "LocalTestOrderLine",
    "LocalTestRequest",
    "LocalTestResponse",
    "_build_list_url",
    "_reload_exact_session_for_snapshot",
    "_serialize_execution_state",
    "router",
]
