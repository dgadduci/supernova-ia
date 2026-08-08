"""Phase-7.4 Twilio WhatsApp inbound webhook router.

The router is a narrow synchronous ``POST`` endpoint that converts
one Twilio WhatsApp inbound form request into the Phase-7.4
acceptance transaction. It is the ONLY HTTP entry point for the new
provider ingress and performs six distinct responsibilities:

1. Read the form fields, the ``X-Twilio-Signature`` header and the
   configured public webhook base URL.
2. Delegate signature validation to the Twilio SDK
   ``RequestValidator`` through the adapter seam.
3. Resolve an existing active client from the canonical ``From``
   number and the active dedicated destination channel from the
   canonical ``To`` number using the existing 5.1 boundary.
4. Build the exact Phase-7.4 ``ProviderInboundMessageCommand`` and
   invoke the coordinator's ``accept`` method with the
   request-owned database session. The coordinator stages exactly
   one pending deferred work item and commits once; the webhook
   path MUST NOT call classifier, recognizer, session/pedido
   staging, intent pipeline, response mapping or outbound staging.
5. Translate the coordinator outcome into the documented TwiML
   shapes: empty TwiML for first acceptance or duplicate, safe
   generic control for the remaining business rejections.
6. Propagate technical failures as ``5xx`` so Twilio can retry;
   never translate a coordinator exception into a business outcome.

The router does NOT own the transaction. The coordinator is the
sole transaction owner. The router MUST NOT call ``commit``,
``rollback``, ``begin``, ``flush``, ``close``, ``expire``,
``refresh`` or any other SQLAlchemy transaction-control method.
The router MUST NOT log the auth token, signature header, raw
body or full form payload.

The handler is intentionally a synchronous ``def`` because the
project's FastAPI surface is sync. The async form read is
isolated in :func:`read_full_form`, the only async dependency
in the module. The dependency reads the complete Twilio form
and delivers a plain ``Mapping[str, str]`` to the handler so the
signature validator sees every parameter Twilio signed.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session as DatabaseSession

from backend.config.settings import load_settings
from backend.dependencies import get_session
from backend.repositories.cliente_repository import ClienteRepository
from backend.services.canal_whatsapp_service import (
    InvalidCanalWhatsappDestination,
)
from backend.services.cliente_service import (
    InvalidWhatsApp,
)
from backend.services.commerce_channel_resolver import (
    CommerceChannelResolver,
    ResolutionStatus,
)
from backend.services.exceptions import (
    InvalidTwilioInboundForm,
    TwilioSignatureUnavailable,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
)
from backend.services.twilio_inbound_adapter import (
    TwilioRequestValidator,
    assert_path_is_safe,
    build_validation_url,
    extract_envelope,
    validate_request,
)

logger = logging.getLogger(__name__)


ROUTE_PATH = "/webhooks/twilio/whatsapp/inbound"

router = APIRouter(tags=["twilio-webhook"])


async def read_full_form(request: Request) -> Mapping[str, str]:
    """Async dependency that reads the complete submitted Twilio form.

    Twilio signs every POST parameter, so the signature validator
    must see every key Twilio submitted (e.g. ``AccountSid``,
    ``ApiVersion``, ``NumMedia``, ``SmsMessageSid``). The
    dependency is the single async seam in the module: it
    performs ``await request.form()`` and returns only the string
    values so the synchronous handler receives the complete
    ``Mapping[str, str]`` without ever needing ``await``.

    The dependency never touches the database, the resolver, the
    coordinator, the adapter or any logging facility, and it
    performs zero downstream work of its own. Signature
    validation, client lookup, channel resolution and core
    processing remain the synchronous handler's responsibility
    so they execute strictly after signature validation.
    """
    form_pairs = await request.form()
    return {
        str(key): value
        for key, value in form_pairs.items()
        if isinstance(value, str)
    }


def _validator_factory(auth_token: str) -> TwilioRequestValidator:
    """Construct the SDK ``RequestValidator`` for the supplied token.

    The factory is isolated so tests can monkeypatch
    ``backend.routers.twilio_webhook._validator_factory`` without
    importing the SDK or providing a real token.
    """
    from twilio.request_validator import RequestValidator

    return RequestValidator(auth_token)


def _empty_twiml_response_body() -> str:
    from twilio.twiml.messaging_response import MessagingResponse

    response = MessagingResponse()
    return str(response)


def _safe_control_twiml_response_body() -> str:
    from twilio.twiml.messaging_response import MessagingResponse

    response = MessagingResponse()
    response.message(
        "Gracias por tu mensaje. En este momento no puedo procesarlo; "
        "intenta nuevamente mas tarde."
    )
    return str(response)


def _resolve_cliente(
    session: DatabaseSession, from_e164: str
) -> tuple[int, bool]:
    """Return ``(cliente_id, activo)`` for the canonical ``From``.

    The helper exists so the router never imports the
    ``ClienteService`` (and its commit/rollback helpers) and never
    raises a service exception to the caller. A missing or
    non-active client is a safe control TwiML outcome and never a
    coordinator invocation.
    """
    cliente = ClienteRepository(session).get_by_whatsapp(from_e164)
    if cliente is None:
        return 0, False
    return int(cliente.id), bool(cliente.activo)


def _resolve_destination(
    session: DatabaseSession, to_e164: str
) -> tuple[int | None, int | None]:
    """Return ``(canal_id, comercio_id)`` for the canonical ``To``.

    The router only acts on ``RESOLVED`` dedicated resolutions; every
    other resolver outcome is a safe control TwiML reply without a
    coordinator call.
    """
    resolution = CommerceChannelResolver(session).resolve_dedicated(
        "twilio", to_e164
    )
    if resolution.status is not ResolutionStatus.RESOLVED:
        return None, None
    return (
        int(resolution.channel_id) if resolution.channel_id is not None else None,
        int(resolution.comercio_id)
        if resolution.comercio_id is not None
        else None,
    )


@router.post(
    ROUTE_PATH,
)
def post_twilio_whatsapp_inbound(
    request: Request,
    x_twilio_signature: str | None = Header(
        default=None, alias="X-Twilio-Signature"
    ),
    session: DatabaseSession = Depends(get_session),  # noqa: B008
    form: Mapping[str, str] = Depends(read_full_form),
) -> Response:
    """Handle one Twilio WhatsApp inbound form request.

    The handler is synchronous so the project's FastAPI surface
    stays sync. The async form read is isolated in the
    :func:`read_full_form` dependency; everything downstream of
    signature validation (client lookup, resolver, coordinator)
    runs in the sync handler.

    The handler returns a raw ``Response`` so the documented
    ``application/xml`` content type and the resolved HTTP status
    survive end-to-end (FastAPI does not serialize a 3-tuple as a
    TwiML payload). The route does not pass the ``Request`` object
    beyond the adapter seam.

    The complete submitted form is delivered by the async
    dependency so the Twilio SDK signature validator receives
    every parameter Twilio signed (e.g. ``AccountSid``,
    ``ApiVersion``, ``NumMedia``, ``SmsMessageSid``). The actual
    query string of the request is also passed so the canonical
    validation URL matches what Twilio signed. Only the four
    documented fields (``MessageSid``, ``From``, ``To``,
    ``Body``) are extracted afterwards for normalization and core
    processing.
    """
    # Defensive path validation: the route path is a literal, but the
    # router re-asserts it so a future refactor cannot smuggle
    # attacker-controlled data into the canonical signature URL.
    assert_path_is_safe(ROUTE_PATH)

    settings = load_settings()
    base_url = settings.twilio_webhook_base_url
    auth_token = settings.twilio_auth_token

    if not base_url or not auth_token:
        logger.info(
            "twilio_webhook_signature_unavailable",
            extra={"route": ROUTE_PATH, "reason": "configuration_missing"},
        )
        return _xml_response("", 403)

    # The async dependency already delivered the complete form
    # mapping. Twilio signs all POST parameters; truncating the
    # form before validation would cause legitimate requests with
    # extra fields to return 403.
    # Use the actual query string of the incoming request so the
    # canonical signature URL matches what Twilio signed.
    query_string = request.url.query

    try:
        validator = _validator_factory(auth_token)
    except Exception:
        logger.exception(
            "twilio_webhook_validator_construction_failed",
            extra={"route": ROUTE_PATH},
        )
        raise

    try:
        build_validation_url(base_url, ROUTE_PATH, query_string)
    except TwilioSignatureUnavailable:
        logger.info(
            "twilio_webhook_signature_unavailable",
            extra={"route": ROUTE_PATH, "reason": "malformed_base_url"},
        )
        return _xml_response("", 403)

    signature_valid = validate_request(
        validator=validator,
        base_url=base_url,
        path=ROUTE_PATH,
        query_string=query_string,
        form=form,
        signature=x_twilio_signature,
    )
    if not signature_valid:
        logger.info(
            "twilio_webhook_signature_rejected",
            extra={"route": ROUTE_PATH},
        )
        return _xml_response("", 403)

    try:
        envelope = extract_envelope(form)
    except InvalidTwilioInboundForm:
        logger.info(
            "twilio_webhook_invalid_form",
            extra={"route": ROUTE_PATH},
        )
        return _xml_response(_safe_control_twiml_response_body(), 200)

    cliente_id, cliente_activo = _resolve_cliente(session, envelope.from_e164)
    if not cliente_activo:
        logger.info(
            "twilio_webhook_unknown_client",
            extra={
                "route": ROUTE_PATH,
                "from_e164_hash": _address_marker(envelope.from_e164),
            },
        )
        return _xml_response(_safe_control_twiml_response_body(), 200)

    canal_id, comercio_id = _resolve_destination(session, envelope.to_e164)
    if canal_id is None or comercio_id is None:
        logger.info(
            "twilio_webhook_unresolved_destination",
            extra={"route": ROUTE_PATH, "canal_id": canal_id},
        )
        return _xml_response(_safe_control_twiml_response_body(), 200)

    try:
        coordinator = ProviderInboundMessageCoordinator(session)
        outcome = coordinator.accept(
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion=envelope.message_sid,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=comercio_id,
                mensaje=envelope.body,
                destinatario_e164=envelope.from_e164,
            )
        )
    except HTTPException:
        raise
    except (InvalidCanalWhatsappDestination, InvalidWhatsApp):
        # Defensive: a downstream race that mutates the canonical
        # numbers between resolution and command construction must
        # never reach the coordinator; it is a safe control reply.
        logger.info(
            "twilio_webhook_canonical_race",
            extra={"route": ROUTE_PATH},
        )
        return _xml_response(_safe_control_twiml_response_body(), 200)

    if outcome.status is ProviderInboundMessageStatus.ACCEPTED:
        logger.info(
            "twilio_webhook_first_processing",
            extra={
                "route": ROUTE_PATH,
                "canal_id": outcome.canal_id,
                "comercio_id": outcome.comercio_id,
                "cliente_id": outcome.cliente_id,
                "receipt_id": outcome.receipt_id,
                "procesamiento_id": outcome.procesamiento_id,
                "resolution_source": outcome.resolution_source,
            },
        )
        return _xml_response(_empty_twiml_response_body(), 200)

    if outcome.status is ProviderInboundMessageStatus.ALREADY_PROCESSED:
        logger.info(
            "twilio_webhook_duplicate_receipt",
            extra={
                "route": ROUTE_PATH,
                "canal_id": outcome.canal_id,
                "comercio_id": outcome.comercio_id,
                "cliente_id": outcome.cliente_id,
                "resolution_source": outcome.resolution_source,
            },
        )
        return _xml_response(_empty_twiml_response_body(), 200)

    logger.info(
        "twilio_webhook_invalid_context",
        extra={
            "route": ROUTE_PATH,
            "canal_id": outcome.canal_id,
            "comercio_id": outcome.comercio_id,
            "cliente_id": outcome.cliente_id,
            "resolution_source": outcome.resolution_source,
        },
    )
    return _xml_response(_safe_control_twiml_response_body(), 200)


def _xml_response(body: str, status_code: int) -> Response:
    """Build a raw ``application/xml`` response with the supplied
    status code. Used to keep Twilio's documented content type while
    supporting both ``200`` (TwiML) and ``403`` (signature rejection)
    responses from the same handler.
    """
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
    )


def _address_marker(address: str) -> str:
    """Return a stable, non-reversible identifier for logging.

    The router must never log the raw provider ``From`` value. The
    marker is the trailing four digits of the canonical E.164
    number; it is the only provider-derived identifier that may
    appear in logs.
    """
    if not isinstance(address, str) or not address:
        return "unknown"
    digits = "".join(ch for ch in address if ch.isdigit())
    if len(digits) < 4:
        return "short"
    return f"tail-{digits[-4:]}"


__all__ = [
    "ROUTE_PATH",
    "post_twilio_whatsapp_inbound",
    "read_full_form",
    "router",
]
