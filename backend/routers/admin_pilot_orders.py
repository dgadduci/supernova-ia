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
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.config.settings import load_settings
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
from backend.services.admin_pilot_emulator_service import (
    EmulatorTestTarget,
    commerce_availability_status,
    emit_admin_emulator_event,
    load_active_emulator_target,
    load_active_installation,
    load_active_session_for_comercio_cliente,
    normalize_destination_e164,
    resolve_bootstrap_target,
    resolve_cliente_e164,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.emulator_control_client import (
    build_emulator_control_client,
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

EMULATOR_MAX_MESSAGE_CHARS: int = 500
EMULATOR_ORIGIN_HEADER: str = "X-Emulator-Test-Origin"
EMULATOR_ORIGIN_VALUE: str = "same-origin"
EMULATOR_REJECTED_MESSAGE: str = (
    "El canal de Twilio Emulator rechazó el mensaje. "
    "Revisá la consola y el panel principal para más detalles."
)

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


def _is_emulator_action_enabled() -> bool:
    """Return ``True`` only when the admin emulator action is
    fully enabled.

    The action requires three conditions to be true simultaneously:

    1. ``TWILIO_PROVIDER_MODE`` is explicitly set to ``emulator``;
    2. ``COMMERCE_ISOLATED_OUTBOUND_ENABLED`` is on so the canonical
       isolated T-C pipeline is the only outbound path;
    3. The emulator configuration is explicit and complete so the
       emulator, T-C adapter and central dispatcher share the same
       Twilio-shaped credentials.

    When any condition is missing the action is hidden in the UI and
    rejected server-side; no real Twilio fallback is invoked.
    """
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - the explicit-mode gate fails closed on every settings load failure
        return False
    if settings.twilio_provider_mode != "emulator":
        return False
    if not bool(settings.commerce_isolated_outbound_enabled):
        return False
    from backend.config.settings import validate_emulator_settings

    try:
        validate_emulator_settings(settings)
    except ValueError:
        return False
    return True


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
            "bootstrap_max_chars": EMULATOR_BOOTSTRAP_MAX_MESSAGE_CHARS,
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
            "emulator_test_max_chars": EMULATOR_MAX_MESSAGE_CHARS,
            "emulator_status_url": (
                f"/admin/pilot/orders/{detail.pedido.id}/emulator-test/status"
            ),
            "emulator_action_url": (
                f"/admin/pilot/orders/{detail.pedido.id}/emulator-test"
            ),
            "emulator_action_enabled": _is_emulator_action_enabled(),
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


EMULATOR_MAX_MESSAGE_CHARS: int = 500
EMULATOR_ORIGIN_HEADER: str = "X-Emulator-Test-Origin"
EMULATOR_ORIGIN_VALUE: str = "same-origin"
EMULATOR_REJECTED_MESSAGE: str = (
    "El canal de Twilio Emulator rechazó el mensaje. "
    "Revisá la consola y el panel principal para más detalles."
)


def _emulator_rejection() -> JSONResponse:
    """Return the documented generic rejection for the emulator path.

    The route never emits a precise diagnostic so the response
    cannot be used to enumerate the operator error class. It is the
    only JSON body the route emits for invalid submissions.
    """
    return JSONResponse(
        status_code=400,
        content={
            "responses": [],
            "message": EMULATOR_REJECTED_MESSAGE,
        },
    )


class EmulatorTestRequest(BaseModel):
    """Bounded request schema for the emulator-test panel action.

    The schema mirrors the local-test schema so the operator's
    mental model stays consistent: the only field is the typed
    message. ``extra='forbid'`` keeps the request surface minimal.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=EMULATOR_MAX_MESSAGE_CHARS)


class EmulatorTestResponse(BaseModel):
    """Successful emulator-test response payload.

    ``synthetic_inbound_id`` is the bounded identifier the browser
    polls against. The schema deliberately omits message bodies,
    signatures, credentials, URLs, exception text or arbitrary
    operator input so the wire payload cannot leak sensitive data.
    """

    model_config = ConfigDict(extra="forbid")

    synthetic_inbound_id: str


class EmulatorStatusRequest(BaseModel):
    """Bounded request schema for the emulator status projection.

    The schema carries the synthetic inbound identifier the browser
    received from the test action. ``extra='forbid'`` keeps the
    surface minimal.
    """

    model_config = ConfigDict(extra="forbid")

    synthetic_inbound_id: str = Field(min_length=1, max_length=128)


class EmulatorStatusResponse(BaseModel):
    """Bounded projection of the existing receipt/outbox state.

    The schema exposes only the bounded status needed by the
    operator console and the simulated outbound text for the
    authenticated test channel. Body, signature, credentials, URLs,
    exception text and arbitrary operator input are intentionally
    absent.

    ``timeline`` is the nullable closed timing projection scoped to
    the exact selected pedido/session/comercio and
    ``synthetic_inbound_id``. Every field is ``None`` until the
    worker reaches the corresponding milestone; the projection is
    never widened to another order, session, commerce or synthetic
    inbound identifier.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "accepted",
        "processed",
        "pending",
        "sent",
        "retryable",
        "terminal",
    ]
    outbound_body: str | None = None
    provider_message_sid: str | None = None
    timeline: EmulatorTimeline


class EmulatorTimeline(BaseModel):
    """Closed nullable timing timeline for one Emulator turn.

    The schema projects exactly six bounded keys; every field is
    nullable until the corresponding milestone is reached. Server
    timestamps travel as UTC ISO-8601 strings and the browser
    converts them to the local timezone through ``HH:MM:SS.mmm``.

    * ``inbound_received_at`` mirrors
      ``recepciones_mensajes_proveedor.fecha_recepcion``.
    * ``llm_requested_at`` is the moment the worker reached the
      existing ``QueryLlm`` boundary.
    * ``llm_finished_at`` is the moment the call finished normally
      or with a captured timeout/error.
    * ``llm_outcome`` is the closed ``completed`` / ``timeout`` /
      ``error`` token.
    * ``processing_finished_at`` mirrors
      ``procesamientos_mensajes_proveedor.fecha_finalizacion``.
    * ``response_staged_at`` mirrors the first outbox row's
      ``fecha_creacion`` when an outbox row exists.

    The schema deliberately omits prompt text, response bodies,
    customer text, exception messages, credentials, secrets and
    arbitrary provider payloads. ``extra='forbid'`` keeps the
    surface closed.
    """

    model_config = ConfigDict(extra="forbid")

    inbound_received_at: str | None = None
    llm_requested_at: str | None = None
    llm_finished_at: str | None = None
    llm_outcome: Literal["completed", "timeout", "error"] | None = None
    processing_finished_at: str | None = None
    response_staged_at: str | None = None


def _emulator_timeline_from_receipt(
    db: Session,
    *,
    receipt: Any,
) -> EmulatorTimeline:
    """Build the closed nullable timeline projection for one receipt.

    The helper reads only the existing provider receipt/work item
    and the first outbox row tied to the exact receipt. It never
    returns data for another receipt, work item, pedido, session
    or commerce: the timeline is the projection of the canonical
    pipeline state for the supplied ``receipt``.

    All server timestamps are emitted as UTC ISO-8601 strings; the
    browser converts them to the local timezone. Missing milestones
    remain ``None`` so the panel can render ``—`` without forcing a
    fallback that could be confused with a backend transition.
    """
    from backend.models import (
        MensajeProveedorSaliente,
        ProcesamientoMensajeProveedor,
    )

    timeline = EmulatorTimeline(
        inbound_received_at=_iso_utc(getattr(receipt, "fecha_recepcion", None)),
    )

    processing_stmt = (
        select(ProcesamientoMensajeProveedor)
        .where(
            ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
            == int(receipt.id)
        )
    )
    processing = db.execute(processing_stmt).unique().scalar_one_or_none()
    if processing is not None:
        timeline.llm_requested_at = _iso_utc(
            getattr(processing, "llm_solicitado_en", None)
        )
        timeline.llm_finished_at = _iso_utc(
            getattr(processing, "llm_finalizado_en", None)
        )
        normalized_outcome = _normalize_llm_outcome(
            getattr(processing, "llm_resultado", None)
        )
        if normalized_outcome is not None:
            timeline.llm_outcome = cast(
                Literal["completed", "timeout", "error"],
                normalized_outcome,
            )
        timeline.processing_finished_at = _iso_utc(
            getattr(processing, "fecha_finalizacion", None)
        )

    outbound_stmt = (
        select(MensajeProveedorSaliente)
        .where(
            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
            == int(receipt.id)
        )
        .order_by(MensajeProveedorSaliente.id.asc())
    )
    first_outbound = db.execute(outbound_stmt).unique().scalars().first()
    if first_outbound is not None:
        timeline.response_staged_at = _iso_utc(
            getattr(first_outbound, "fecha_creacion", None)
        )
    return timeline


def _iso_utc(value: Any) -> str | None:
    """Render an aware datetime as a UTC ISO-8601 string.

    Naive datetimes are interpreted as UTC so the projection never
    silently re-labels a wall-clock value. ``None`` and any other
    type collapse to ``None`` so the panel can render ``—`` for
    unavailable milestones.
    """
    from datetime import datetime, timezone

    if value is None:
        return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _normalize_llm_outcome(value: Any) -> str | None:
    """Coerce a stored LLM outcome into the closed wire token.

    Unknown or empty values collapse to ``None`` so the panel can
    render ``—`` rather than emit an arbitrary token. The function
    never raises so a malformed stored value cannot break the
    status projection.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"completed", "timeout", "error"}:
        return normalized
    return None


def _emulator_outbox_summary(
    db: Session,
    *,
    pedido_id: int,
    target: EmulatorTestTarget,
    synthetic_inbound_id: str,
) -> EmulatorStatusResponse:
    """Project the existing receipt/outbox state for the operator.

    The helper reads only the existing provider receipt/outbox rows
    tied to the exact selected pedido/session/comercio. It never
    queries the synthetic inbound identifier directly: the bounded
    state is the projection of the canonical pipeline.

    The closed nullable timeline is always returned alongside the
    existing projection so the browser can render the bounded
    server-side milestones. Missing receipt, work item or outbox
    rows yield an all-``None`` timeline rather than a 404 — the
    status value is the documented branching signal.
    """
    from sqlalchemy import select

    from backend.models import (
        MensajeProveedorSaliente,
        OutboundProviderMessageState,
        RecepcionMensajeProveedor,
    )

    empty_timeline = EmulatorTimeline()
    receipt_stmt = (
        select(RecepcionMensajeProveedor)
        .where(RecepcionMensajeProveedor.comercio_id == target.comercio_id)
        .where(
            RecepcionMensajeProveedor.identificador_recepcion
            == synthetic_inbound_id
        )
    )
    receipt = db.execute(receipt_stmt).unique().scalar_one_or_none()
    if receipt is None:
        return EmulatorStatusResponse(
            status="accepted",
            outbound_body=None,
            provider_message_sid=None,
            timeline=empty_timeline,
        )

    timeline = _emulator_timeline_from_receipt(db, receipt=receipt)

    outbound_stmt = (
        select(MensajeProveedorSaliente)
        .where(
            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
            == int(receipt.id)
        )
        .order_by(MensajeProveedorSaliente.id.desc())
    )
    outbound_rows = list(
        db.execute(outbound_stmt).unique().scalars()
    )
    if not outbound_rows:
        return EmulatorStatusResponse(
            status="processed",
            outbound_body=None,
            provider_message_sid=None,
            timeline=timeline,
        )
    first = outbound_rows[0]
    estado = str(getattr(first, "estado", "") or "")
    sid = getattr(first, "identificador_proveedor", None)
    cuerpo = getattr(first, "cuerpo", None)
    if estado == OutboundProviderMessageState.ACCEPTED.value:
        status = "sent"
    elif estado == OutboundProviderMessageState.PENDING.value or estado == OutboundProviderMessageState.LEASED.value:
        status = "pending"
    elif estado == OutboundProviderMessageState.RETRYABLE.value:
        status = "retryable"
    elif estado == OutboundProviderMessageState.FAILED_TERMINAL.value:
        status = "terminal"
    elif estado == OutboundProviderMessageState.DELIVERED.value:
        status = "sent"
    else:
        status = "processed"
    return EmulatorStatusResponse(
        status=status,
        outbound_body=str(cuerpo) if isinstance(cuerpo, str) else None,
        provider_message_sid=str(sid) if sid is not None else None,
        timeline=timeline,
    )


@router.post("/{pedido_id}/emulator-test", response_class=JSONResponse)
def emulator_test_message(
    pedido_id: Annotated[str, Path()],
    payload: EmulatorTestRequest,
    db: Annotated[Session, Depends(get_session)],
    origin_header: Annotated[
        str | None, Header(alias=EMULATOR_ORIGIN_HEADER)
    ] = None,
) -> JSONResponse:
    """Panel-controlled Twilio emulator test action.

    The route is the only admin/pilot surface that drives the
    twilio emulator. It validates the exact selected active
    Session/Pedido/Cliente/Comercio identity, the dedicated
    channel, the active T-C installation and the operator-pinned
    emulator configuration before asking the emulator to deliver
    the inbound through the configured T-C webhook.

    The route never calls the coordinator, worker, dispatcher,
    central Twilio or T-C directly. It only invokes the
    authenticated emulator inbound control surface and returns the
    synthetic inbound identifier the browser uses to poll the
    existing receipt/outbox state through
    :func:`emulator_test_status`.

    Every failure branch returns the documented generic rejection
    so the operator cannot probe which invariant failed.
    """
    if origin_header != EMULATOR_ORIGIN_VALUE:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_origin"
        )
        return _emulator_rejection()

    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_pedido_id"
        )
        return _emulator_rejection()

    target = load_active_emulator_target(db, parsed_id)
    if target is None:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_target"
        )
        return _emulator_rejection()

    settings = load_settings()
    if (
        settings.twilio_provider_mode != "emulator"
        or not bool(settings.commerce_isolated_outbound_enabled)
    ):
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_rejection()
    from backend.config.settings import validate_emulator_settings

    try:
        validate_emulator_settings(settings)
    except ValueError:
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_rejection()

    if (
        commerce_availability_status(db, comercio_id=target.comercio_id)
        is not CommerceAvailabilityStatus.AVAILABLE
    ):
        emit_admin_emulator_event(
            outcome="rejected", reason="unavailable_commerce"
        )
        return _emulator_rejection()

    if load_active_installation(
        db, comercio_id=target.comercio_id
    ) is None:
        emit_admin_emulator_event(
            outcome="rejected", reason="inactive_installation"
        )
        return _emulator_rejection()

    emulator_client = build_emulator_control_client(
        base_url=settings.twilio_emulator_base_url,
        control_token=settings.twilio_emulator_control_token,
        timeout_seconds=float(
            settings.twilio_emulator_http_timeout_seconds
        ),
    )
    if emulator_client is None:
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_rejection()

    source_e164 = resolve_cliente_e164(
        db, cliente_id=target.cliente_id
    )
    destination_e164 = normalize_destination_e164(
        target.canal_destination_e164
    )
    if source_e164 is None or destination_e164 is None:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid"
        )
        return _emulator_rejection()

    try:
        response = emulator_client.submit_inbound(
            source_e164=source_e164,
            destination_e164=destination_e164,
            body=payload.message,
        )
    except Exception:  # noqa: BLE001 - the emulator path fails closed on every transport failure
        emit_admin_emulator_event(
            outcome="unavailable", reason="transport"
        )
        return _emulator_rejection()

    emit_admin_emulator_event(outcome="submitted")

    body = EmulatorTestResponse(
        synthetic_inbound_id=response.synthetic_inbound_id,
    ).model_dump()
    return JSONResponse(status_code=200, content=body)


@router.post(
    "/{pedido_id}/emulator-test/status",
    response_class=JSONResponse,
)
def emulator_test_status(
    pedido_id: Annotated[str, Path()],
    payload: EmulatorStatusRequest,
    db: Annotated[Session, Depends(get_session)],
    origin_header: Annotated[
        str | None, Header(alias=EMULATOR_ORIGIN_HEADER)
    ] = None,
) -> JSONResponse:
    """Read-only projection of the existing receipt/outbox state.

    The status projection is scoped to the exact selected
    pedido/session/comercio and the exact synthetic inbound
    identifier emitted by the test action. It never returns data
    for another pedido, session, commerce or synthetic inbound
    identifier.

    The disabled-emulator guard runs BEFORE any Pedido, Session,
    receipt or outbox read so the route fails closed at the
    configuration boundary and never opens a database connection
    or invokes the worker, dispatcher, T-C or Twilio when the
    emulator action is unavailable. The helper reads the existing
    provider receipt/outbox rows through the canonical repository
    so the worker remains the single owner of the durable state.
    The helper never invokes the worker or dispatcher
    synchronously.
    """
    if origin_header != EMULATOR_ORIGIN_VALUE:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_origin"
        )
        return _emulator_rejection()

    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_pedido_id"
        )
        return _emulator_rejection()

    if not _is_emulator_action_enabled():
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_rejection()

    target = load_active_emulator_target(db, parsed_id)
    if target is None:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_target"
        )
        return _emulator_rejection()

    summary = _emulator_outbox_summary(
        db,
        pedido_id=parsed_id,
        target=target,
        synthetic_inbound_id=payload.synthetic_inbound_id,
    )
    body = summary.model_dump()
    return JSONResponse(status_code=200, content=body)


EMULATOR_BOOTSTRAP_MAX_MESSAGE_CHARS: int = 500
EMULATOR_BOOTSTRAP_ORIGIN_HEADER: str = "X-Emulator-Test-Origin"
EMULATOR_BOOTSTRAP_ORIGIN_VALUE: str = "same-origin"
EMULATOR_BOOTSTRAP_REJECTED_MESSAGE: str = (
    "El canal de Twilio Emulator rechazó el mensaje. "
    "Revisá la consola y el panel principal para más detalles."
)


def _emulator_bootstrap_rejection() -> JSONResponse:
    """Return the documented generic rejection for the bootstrap path.

    The route never emits a precise diagnostic so the response
    cannot be used to enumerate the operator error class. It is the
    only JSON body the route emits for invalid submissions.
    """
    return JSONResponse(
        status_code=400,
        content={
            "responses": [],
            "message": EMULATOR_BOOTSTRAP_REJECTED_MESSAGE,
        },
    )


class EmulatorBootstrapRequest(BaseModel):
    """Bounded request schema for the bootstrap panel action.

    The schema accepts exactly the three documented fields. The
    ``extra='forbid'`` config keeps the surface minimal so the
    browser cannot smuggle in E.164 addresses, URLs, credentials
    or arbitrary provider payloads. ``cliente_id`` and ``comercio_id``
    are the operator-selected test identity; the server resolves the
    canonical provider addresses from the database.

    ``message`` enforces a positive character budget via
    ``max_length`` and a server-side non-blank validator that
    rejects ``""``, ASCII spaces, tabs and newlines. ``min_length=1``
    alone accepts whitespace-only payloads (e.g. ``"   "``,
    ``"\\t\\n"``), so the explicit ``field_validator`` is the
    authoritative guard against contacting the Twilio Emulator with
    an empty operator body. The original message is preserved
    untouched when it carries at least one non-whitespace character;
    the validator never normalises a valid submission.
    """

    model_config = ConfigDict(extra="forbid")

    cliente_id: int = Field(gt=0)
    comercio_id: int = Field(gt=0)
    message: str = Field(max_length=EMULATOR_BOOTSTRAP_MAX_MESSAGE_CHARS)

    @field_validator("message")
    @classmethod
    def _require_non_blank_message(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("message must not be blank")
        return value


class EmulatorBootstrapResponse(BaseModel):
    """Bounded bootstrap response payload.

    ``synthetic_inbound_id`` is the bounded identifier the browser
    used to poll the receipt/outbox state. The schema deliberately
    omits message bodies, signatures, credentials, URLs, exception
    text, client/commerce identifiers or arbitrary operator input
    so the wire payload cannot leak sensitive data.
    """

    model_config = ConfigDict(extra="forbid")

    synthetic_inbound_id: str


@router.post("/emulator-bootstrap", response_class=JSONResponse)
def emulator_bootstrap_inbound(
    payload: EmulatorBootstrapRequest,
    db: Annotated[Session, Depends(get_session)],
    origin_header: Annotated[
        str | None, Header(alias=EMULATOR_BOOTSTRAP_ORIGIN_HEADER)
    ] = None,
) -> JSONResponse:
    """Bootstrap a clean emulator inbound from the Admin/Pilot list.

    The route is the only entry point that drives the emulator
    inbound from an operator-selected cliente/comercio pair. It
    validates the exact active Cliente, the canonical dedicated
    Twilio channel for the comercio, the active T-C installation
    and the commerce availability BEFORE invoking the emulator.

    The route rejects the submission when the cliente/comercio
    pair already has an active Session so the bootstrap action
    cannot race with an existing context. It never closes,
    replaces or mutates that session or pedido.

    The route never calls the coordinator, worker, dispatcher,
    central Twilio or T-C directly. It only invokes the
    authenticated emulator inbound control surface and returns the
    synthetic inbound identifier the browser uses to refresh the
    existing order list. The provider worker remains responsible
    for creating the active Session and the draft Pedido.

    The route never commits, rolls back, flushes, refreshes,
    begins or closes the database session. The request-level
    dependency remains the transaction owner. The route never
    creates a Session, Pedido, Cliente, channel, installation,
    receipt, processing row or outbox row directly.

    Every failure branch returns the documented generic rejection
    so the operator cannot probe which invariant failed.
    """
    if origin_header != EMULATOR_BOOTSTRAP_ORIGIN_VALUE:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_origin"
        )
        return _emulator_bootstrap_rejection()

    settings = load_settings()
    if (
        settings.twilio_provider_mode != "emulator"
        or not bool(settings.commerce_isolated_outbound_enabled)
    ):
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_bootstrap_rejection()
    from backend.config.settings import validate_emulator_settings

    try:
        validate_emulator_settings(settings)
    except ValueError:
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_bootstrap_rejection()

    target = resolve_bootstrap_target(
        db,
        cliente_id=payload.cliente_id,
        comercio_id=payload.comercio_id,
    )
    if target is None:
        emit_admin_emulator_event(
            outcome="rejected", reason="invalid_target"
        )
        return _emulator_bootstrap_rejection()

    if (
        load_active_session_for_comercio_cliente(
            db,
            cliente_id=payload.cliente_id,
            comercio_id=payload.comercio_id,
        )
        is not None
    ):
        emit_admin_emulator_event(
            outcome="rejected", reason="active_context"
        )
        return _emulator_bootstrap_rejection()

    emulator_client = build_emulator_control_client(
        base_url=settings.twilio_emulator_base_url,
        control_token=settings.twilio_emulator_control_token,
        timeout_seconds=float(
            settings.twilio_emulator_http_timeout_seconds
        ),
    )
    if emulator_client is None:
        emit_admin_emulator_event(
            outcome="unavailable", reason="emulator_disabled"
        )
        return _emulator_bootstrap_rejection()

    try:
        response = emulator_client.submit_inbound(
            source_e164=target.cliente_e164,
            destination_e164=target.canal_destination_e164,
            body=payload.message,
        )
    except Exception:  # noqa: BLE001 - the emulator path fails closed on every transport failure
        emit_admin_emulator_event(
            outcome="unavailable", reason="transport"
        )
        return _emulator_bootstrap_rejection()

    emit_admin_emulator_event(outcome="submitted")

    body = EmulatorBootstrapResponse(
        synthetic_inbound_id=response.synthetic_inbound_id,
    ).model_dump()
    return JSONResponse(status_code=200, content=body)


__all__ = [
    "EMULATOR_BOOTSTRAP_MAX_MESSAGE_CHARS",
    "EMULATOR_BOOTSTRAP_ORIGIN_HEADER",
    "EMULATOR_BOOTSTRAP_ORIGIN_VALUE",
    "EMULATOR_BOOTSTRAP_REJECTED_MESSAGE",
    "LOCAL_TEST_EXECUTION_STATE_EMPTY_SCHEMA_VERSION",
    "LOCAL_TEST_MAX_MESSAGE_CHARS",
    "LOCAL_TEST_ORIGIN_HEADER",
    "LOCAL_TEST_ORIGIN_VALUE",
    "_ESTADO_VALUES",
    "EmulatorBootstrapRequest",
    "EmulatorBootstrapResponse",
    "EmulatorStatusRequest",
    "EmulatorStatusResponse",
    "EmulatorTestRequest",
    "EmulatorTestResponse",
    "EmulatorTimeline",
    "LocalTestExecutionState",
    "LocalTestOrderLine",
    "LocalTestRequest",
    "LocalTestResponse",
    "_build_list_url",
    "_emulator_bootstrap_rejection",
    "_emulator_outbox_summary",
    "_emulator_rejection",
    "_emulator_timeline_from_receipt",
    "_is_confirmed_clean_context",
    "_is_single_status_intent",
    "_iso_utc",
    "_load_confirmed_local_test_session",
    "_normalize_llm_outcome",
    "_reload_exact_session_for_snapshot",
    "_serialize_execution_state",
    "emulator_bootstrap_inbound",
    "emulator_test_message",
    "emulator_test_status",
    "router",
]
