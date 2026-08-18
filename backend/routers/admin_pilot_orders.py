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

For the exact selected non-``BORRADOR`` pedido with a clean pending
context the route additionally accepts exactly one
``consultar_estado_pedido`` intent classified by the existing
classifier. The classifier is invoked once as a language
interpreter only; every other outcome returns the documented
generic local rejection without invoking the message processor, the
global dispatcher or any mutating handler.

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

Local pilot styling diagnostic handoff (subphase 7): the
successful local-test response additionally carries a closed
``outbound_style`` projection of the latest styling attempt for
the exact selected Session. The projection is typed, request-scoped
and ephemeral: it is delivered only inside the HTTP response of
the local-test route and is never persisted, never sent to the
provider outbox, never used as business input and never reaches
Twilio. The projection deliberately contains only the closed
shape documented in :class:`OutboundStyleDiagnostic` and never
the rendered messages, prefix/suffix, the prompt, the flavor
instruction, identifiers, timing, exception detail or arbitrary
event payloads. The route remains list-only for every outlier
it rejects: rejections use the documented generic payload and
never carry the diagnostic.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path as PathLib
from typing import Annotated, Literal, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.dependencies import get_session, require_admin_pilot_basic
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_style_diagnostic,
)
from backend.intents.orchestration.order_status_query import (
    process_initial_order_status_query,
)
from backend.intents.schemas.intent_classification import (
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.pending_intents import PendingIntents
from backend.llm.intent_classifier import IntentClassifier
from backend.models import (
    EstadoPedido,
    EstadoSession,
    Pedido,
)
from backend.models import (
    Session as SessionModel,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.outbound_response_mapper import (
    build_customer_responses_with_diagnostic,
)
from backend.services.outbound_response_styler import StyleDiagnostic
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


def _load_confirmed_local_test_session(
    db: Session,
    pedido_id: int,
) -> tuple[Pedido, SessionModel] | None:
    """Load the exact Pedido/Session for the confirmed-order branch.

    The loader mirrors the identity, ownership and active-session
    contract of :func:`_load_local_test_session` but accepts the
    pedido in any non-``BORRADOR`` state so the route can answer a
    natural-language status question for an already confirmed
    pedido. It returns ``None`` for every other shape — including a
    missing pedido, a non-positive id, a missing or re-pointed
    Session, an inactive Session, a cliente/comercio mismatch or a
    pedido that is still in ``BORRADOR`` — so the caller can emit
    the documented generic rejection without leaking which
    invariant failed.

    The loader never searches for another session, a successor
    session or an alternative active session for the same
    cliente/comercio; it returns the exact identity or ``None``.
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
    if pedido.estado_pedido == EstadoPedido.BORRADOR:
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


def _commerce_availability_outcome(
    db: Session,
    exact_session: SessionModel,
) -> CommerceAvailabilityStatus:
    """Evaluate ``CommerceAvailabilityService`` for the exact Session.

    The helper reads only ``exact_session.id_comercio`` and never
    inspects lifecycle codes, descriptions or labels. A missing or
    non-positive ``id_comercio`` collapses to the documented
    unavailable outcome so the caller can branch on a single
    attribute. The session is the unique transaction owner; the
    policy itself never commits or rolls back.

    The helper is the only place in the route that touches
    ``CommerceAvailabilityService``. It is reused by both the
    ``BORRADOR`` branch and the confirmed/no-``BORRADOR`` branch so
    the panel-local test channel can never process a message for
    a blocked, expired-trial or quota-exhausted commerce.
    """
    comercio_id = getattr(exact_session, "id_comercio", None)
    if not isinstance(comercio_id, int) or comercio_id <= 0:
        return CommerceAvailabilityStatus.UNAVAILABLE
    availability = CommerceAvailabilityService(db).evaluate(comercio_id)
    return availability.status


def _is_confirmed_clean_context(
    raw_context_type: object,
    raw_pending_intents: object,
) -> bool:
    """Return ``True`` only for a confirmed target with a clean
    pending context.

    The route must fail closed for any active or queued pending
    state, malformed pending JSON or any non-``None``
    ``context_type``. The accepted shape is exactly:
    ``context_type`` strictly ``None`` AND ``pending_intents``
    absent, an empty dict or a parsed
    :class:`PendingIntents` carrying ``active is None`` and an
    empty ``queue``. Any other shape — a non-``None``
    ``context_type`` (including the empty string), a dict that
    fails :meth:`PendingIntents.model_validate`, a parsed active
    intent or a non-empty queue — returns ``False`` so the route
    rejects before invoking the classifier or any business
    orchestration.

    Validation errors are swallowed and never propagated: the
    helper returns ``False`` for any malformed JSON or
    schema-incompatible shape without exposing validation detail,
    pending JSON or exception text to the caller.
    """
    if raw_context_type is not None:
        return False
    if raw_pending_intents is None:
        return True
    if isinstance(raw_pending_intents, dict) and not raw_pending_intents:
        return True
    if not isinstance(raw_pending_intents, dict):
        return False
    try:
        parsed = PendingIntents.model_validate(raw_pending_intents)
    except ValidationError:
        return False
    return parsed.active is None and parsed.queue == []


def _is_single_status_intent(
    classification: object,
) -> bool:
    """Return ``True`` only when the classifier produced exactly one
    :class:`IntentName.CONSULTAR_ESTADO_PEDIDO` intent.

    Any other shape — missing intents, multiple intents, a
    non-status intent, a non-string intent, or any value that does
    not implement the documented ``intents`` surface — returns
    ``False`` so the route fails closed before invoking any
    business orchestration. The classifier remains a language
    interpreter only: the route accepts the result precisely when
    it is the one allowlisted intent, and rejects every other
    outcome.
    """
    intents = getattr(classification, "intents", None)
    if not isinstance(intents, list) or len(intents) != 1:
        return False
    item = intents[0]
    intent_value = getattr(item, "intent", None)
    if isinstance(intent_value, IntentName):
        return intent_value == IntentName.CONSULTAR_ESTADO_PEDIDO
    if isinstance(intent_value, str):
        return intent_value == IntentName.CONSULTAR_ESTADO_PEDIDO.value
    return False


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


class OutboundStyleDiagnostic(BaseModel):
    """Closed, request-scoped styling diagnostic for the local-test
    channel.

    The schema mirrors the documented spec field set exactly:

    * ``outcome`` — one of ``"applied"``, ``"fallback"`` or
      ``"not_attempted"`` so the operator can distinguish an
      attempted styling from a no-op the panel would otherwise
      conflate with an ineligible response.
    * ``eligible_count`` and ``applied_count`` — bounded
      non-negative integers mirroring the observability event.
    * ``fallback_category`` — only present when ``outcome`` is
      ``"fallback"``; the bounded allowlisted token that
      explains the failure mode (transport, wrapper, etc.).
    * ``flavor_code`` — only present when the selected flavor
      was usable for the attempt; NEVER present when the flavor
      was ``neutro``, missing, inactive or had no instruction.
    * ``response_types`` — the ordered allowlisted
      ``response_type`` tokens the attempt touched (eligible
      items only, never the rendered message text).
    * ``template_version`` — the static template identity
      published by the styler prompt template.

    The schema deliberately forbids every other field so the
    diagnostic cannot leak the rendered prompt, the flavor
    instruction, raw customer text, factual response text,
    prefix/suffix, identifiers, timing, exception detail,
    model output or arbitrary event payloads. The companion is
    ephemeral, request-scoped and never persisted.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["applied", "fallback", "not_attempted"]
    eligible_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    fallback_category: str | None = None
    flavor_code: str | None = None
    response_types: list[str]
    template_version: str


class LocalTestResponse(BaseModel):
    """Successful local-test response payload.

    The payload is built explicitly so the route cannot accidentally
    serialize the raw Session, Pedido or ``pending_intents``.
    ``responses`` carries the mapped customer turns; ``execution_state``
    carries the closed snapshot for the existing state cells;
    ``order_lines`` carries the typed, JSON-safe line snapshot for
    the exact selected Pedido so the browser can refresh the
    centre-column lines list in place. ``outbound_style`` carries
    the closed request-scoped styling diagnostic for the latest
    local turn so the panel can show the operator whether an
    active selected flavor was applied, fell back or was not
    attempted. The schema rejects any extra member so a future
    regression that starts leaking raw fields would fail at
    runtime.
    """

    model_config = ConfigDict(extra="forbid")

    responses: list[dict[str, str]]
    execution_state: LocalTestExecutionState
    order_lines: list[LocalTestOrderLine]
    outbound_style: OutboundStyleDiagnostic


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

    For the exact selected non-``BORRADOR`` pedido with a clean
    pending context the route accepts ONLY a single
    :class:`IntentName.CONSULTAR_ESTADO_PEDIDO` intent. The
    classifier is invoked exactly once as a language interpreter;
    every other outcome — non-status intent, multi-intent,
    classifier transport/schema failure, pending active/queue
    activity, malformed pending JSON or any identity/ownership
    inconsistency — returns the documented generic local
    rejection and never invokes the normal message processor, the
    global dispatcher or any mutating handler. The non-draft path
    reuses :func:`process_initial_order_status_query` and
    :func:`build_customer_responses` for the exact same
    pedido/session identity and projects the same safe snapshot
    used by the draft branch.
    """
    if origin_header != LOCAL_TEST_ORIGIN_VALUE:
        return _reject_local_test("missing same-origin header")

    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        return _reject_local_test("invalid pedido id")

    loaded = _load_local_test_session(db, parsed_id)
    if loaded is not None:
        _, exact_session = loaded
        if (
            _commerce_availability_outcome(db, exact_session)
            is not CommerceAvailabilityStatus.AVAILABLE
        ):
            return _reject_local_test("comercio no disponible")
        responses, style_diagnostic = process_incoming_message_with_style_diagnostic(
            db, exact_session, payload.message
        )
    else:
        confirmed = _load_confirmed_local_test_session(db, parsed_id)
        if confirmed is None:
            return _reject_local_test("target not eligible")
        _, exact_session = confirmed
        if (
            _commerce_availability_outcome(db, exact_session)
            is not CommerceAvailabilityStatus.AVAILABLE
        ):
            return _reject_local_test("comercio no disponible")

        if not _is_confirmed_clean_context(
            raw_context_type=exact_session.context_type,
            raw_pending_intents=exact_session.pending_intents,
        ):
            return _reject_local_test("pending context not clean")

        classifier = IntentClassifier()
        try:
            classification: IntentClassificationResult = classifier.query(
                payload.message
            )
        except Exception:  # noqa: BLE001 - classifier failures fail closed
            return _reject_local_test("classifier failure")

        if not _is_single_status_intent(classification):
            return _reject_local_test("not a single status intent")

        classified_message = classification.intents[0].mensaje
        processed_intent = process_initial_order_status_query(
            db, exact_session, classified_message
        )
        responses, style_diagnostic = build_customer_responses_with_diagnostic(
            db, exact_session, [processed_intent]
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
        outbound_style=_serialize_outbound_style_diagnostic(style_diagnostic),
    )
    return JSONResponse(
        status_code=200,
        content=response_payload.model_dump(),
    )


def _serialize_outbound_style_diagnostic(
    diagnostic: StyleDiagnostic,
) -> OutboundStyleDiagnostic:
    """Project a :class:`StyleDiagnostic` into the closed
    :class:`OutboundStyleDiagnostic` wire schema.

    The serializer is the only place that builds the
    outward-facing representation of the diagnostic. It pulls
    the documented closed fields exclusively via the dataclass
    surface so a future field added to :class:`StyleDiagnostic`
    cannot leak into the wire payload. The serializer never
    inspects the database, the configuration or the LLM.
    """
    allowed_outcomes: tuple[Literal["applied", "fallback", "not_attempted"], ...] = (
        "applied",
        "fallback",
        "not_attempted",
    )
    outcome = diagnostic.outcome
    if outcome not in allowed_outcomes:
        raise ValueError(
            f"unexpected outbound style outcome: {outcome!r}"
        )
    return OutboundStyleDiagnostic(
        outcome=cast(
            Literal["applied", "fallback", "not_attempted"], outcome
        ),
        eligible_count=int(diagnostic.eligible_count),
        applied_count=int(diagnostic.applied_count),
        fallback_category=(
            diagnostic.fallback_category
            if diagnostic.fallback_category is not None
            else None
        ),
        flavor_code=(
            diagnostic.flavor_code if diagnostic.flavor_code is not None else None
        ),
        response_types=list(diagnostic.response_types),
        template_version=diagnostic.template_version,
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
    "_is_confirmed_clean_context",
    "_is_single_status_intent",
    "_load_confirmed_local_test_session",
    "_reload_exact_session_for_snapshot",
    "_serialize_execution_state",
    "router",
]
