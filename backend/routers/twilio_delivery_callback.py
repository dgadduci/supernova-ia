"""Phase-5.6 Twilio delivery status callback router.

The router is the only HTTP surface for the inbound provider delivery
status callback. It performs six distinct responsibilities:

1. Read the form fields, the ``X-Twilio-Signature`` header and the
   configured public webhook base URL.
2. Delegate signature validation to the Twilio SDK
   ``RequestValidator`` through the adapter seam.
3. Normalize the two required callback fields (``MessageSid``,
   ``MessageStatus``) into the canonical envelope.
4. Delegate the monotonic state mutation to the callback service.
5. Translate the typed service outcome into the documented HTTP
   status codes: ``204`` for every safe no-op (invalid signature,
   unknown SID, duplicate, regression, malformed valid form) and
   ``204`` for a successful monotonic transition. Twilio does not
   care which branch was taken; the router never embeds the
   business state in the response body.
6. Propagate technical failures as ``5xx`` so Twilio can retry;
   never translate a service exception into a business outcome.

The router does NOT own the transaction. The callback service owns
a narrow persistence transaction per call. The router MUST NOT call
``commit``, ``rollback``, ``begin``, ``flush``, ``close``,
``expire``, ``refresh`` or any other SQLAlchemy transaction-control
method. The router MUST NOT log the auth token, signature header,
raw body or full form payload.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from backend.config.settings import load_settings
from backend.dependencies import get_session
from backend.observability import (
    COMPONENT_CALLBACK,
    COMPONENT_DATABASE,
    EVENT_CALLBACK_OUTCOME,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    categorize_sqlalchemy_error,
    emit_event,
)
from backend.services.exceptions import (
    InvalidTwilioDeliveryCallbackForm,
    TwilioSignatureUnavailable,
)
from backend.services.twilio_delivery_callback_adapter import (
    extract_envelope,
    validate_request,
)
from backend.services.twilio_delivery_callback_service import (
    TwilioDeliveryCallbackService,
)
from backend.services.twilio_inbound_adapter import (
    TwilioRequestValidator,
    assert_path_is_safe,
)

logger = logging.getLogger(__name__)


ROUTE_PATH = "/webhooks/twilio/whatsapp/status"

router = APIRouter(tags=["twilio-webhook"])


async def read_full_form(request: Request) -> Mapping[str, str]:
    """Async dependency that reads the complete submitted Twilio
    callback form.

    Twilio signs every POST parameter, so the signature validator
    must see every key Twilio submitted. The dependency is the
    single async seam in the module.
    """
    form_pairs = await request.form()
    return {
        str(key): value
        for key, value in form_pairs.items()
        if isinstance(value, str)
    }


def _validator_factory(auth_token: str) -> TwilioRequestValidator:
    """Construct the SDK ``RequestValidator`` for the supplied
    token. The factory is isolated so tests can monkeypatch it
    without importing the SDK or providing a real token."""
    from twilio.request_validator import RequestValidator

    return RequestValidator(auth_token)


def _xml_response(body: str, status_code: int) -> Response:
    """Build a raw ``application/xml`` response with the supplied
    status code."""
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
    )


@router.post(ROUTE_PATH)
def post_twilio_whatsapp_status(
    request: Request,
    x_twilio_signature: str | None = Header(
        default=None, alias="X-Twilio-Signature"
    ),
    session: DatabaseSession = Depends(get_session),  # noqa: B008
    form: Mapping[str, str] = Depends(read_full_form),
) -> Response:
    """Handle one Twilio WhatsApp delivery status callback.

    The handler returns a raw ``Response`` so the documented
    ``application/xml`` content type and the resolved HTTP status
    survive end-to-end. The route does not pass the ``Request``
    object beyond the adapter seam.
    """
    assert_path_is_safe(ROUTE_PATH)

    settings = load_settings()
    base_url = settings.twilio_webhook_base_url
    auth_token = settings.twilio_auth_token

    if not base_url or not auth_token:
        logger.info(
            "twilio_callback_signature_unavailable",
            extra={"route": ROUTE_PATH, "reason": "configuration_missing"},
        )
        return _xml_response("", 403)

    query_string = request.url.query

    try:
        validator = _validator_factory(auth_token)
    except Exception:
        logger.exception(
            "twilio_callback_validator_construction_failed",
            extra={"route": ROUTE_PATH},
        )
        raise

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
            "twilio_callback_signature_rejected",
            extra={"route": ROUTE_PATH},
        )
        return _xml_response("", 403)

    try:
        envelope = extract_envelope(form)
    except InvalidTwilioDeliveryCallbackForm:
        logger.info(
            "twilio_callback_invalid_form",
            extra={"route": ROUTE_PATH},
        )
        return _xml_response("", 204)
    except TwilioSignatureUnavailable:
        logger.info(
            "twilio_callback_signature_unavailable",
            extra={"route": ROUTE_PATH, "reason": "malformed_base_url"},
        )
        return _xml_response("", 403)

    service = TwilioDeliveryCallbackService(session)
    try:
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor=envelope.message_sid,
            message_status=envelope.message_status,
        )
    except SQLAlchemyError as exc:
        emit_event(
            event=EVENT_DATABASE_TECHNICAL_FAILURE,
            component=COMPONENT_DATABASE,
            failure_category=categorize_sqlalchemy_error(exc),
            exception_type=type(exc).__name__,
        )
        raise

    logger.info(
        "twilio_callback_applied",
        extra={
            "route": ROUTE_PATH,
            "outcome": result.outcome.value,
            "outbox_id": result.mensaje_id,
            "estado_anterior": result.estado_anterior,
            "estado_nuevo": result.estado_nuevo,
        },
    )
    emit_event(
        event=EVENT_CALLBACK_OUTCOME,
        component=COMPONENT_CALLBACK,
        outcome=str(result.outcome.value),
        outbox_id=int(result.mensaje_id) if result.mensaje_id is not None else None,
        durable_state=(
            str(result.estado_nuevo)
            if result.estado_nuevo is not None
            else None
        ),
    )
    return _xml_response("", 204)


__all__ = [
    "ROUTE_PATH",
    "post_twilio_whatsapp_status",
    "read_full_form",
    "router",
]