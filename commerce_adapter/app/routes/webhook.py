"""Merchant Twilio webhook route for the T-C adapter.

The route is the only HTTP entry point that accepts a Twilio webhook
for this merchant. It performs six narrow responsibilities:

1. Read the complete Twilio form via :func:`read_full_form` so the
   signature validator sees every parameter Twilio signed.
2. Validate ``X-Twilio-Signature`` against the exact public URL of the
   configured merchant base URL plus the request path and the actual
   query string, and against the submitted form.
3. Normalize the four documented Twilio fields into the canonical
   event.
4. Sign the canonical event with HMAC-SHA256 using the installation
   secret and POST it to NovaOrders.
5. Translate the NovaOrders outcome into the empty TwiML
   ``<Response></Response>`` only when NovaOrders confirms acceptance
   or a documented reject outcome.
6. Return ``502`` with an empty body when NovaOrders is unreachable so
   Twilio retries.

The route never logs body, phone, token, signature, profile names or
raw Twilio payloads. It never embeds a ``<Message>`` in the
acknowledgement and never sends a real Twilio API call in the webhook
path.

The async form read is isolated in :func:`read_full_form` so the rest
of the handler stays synchronous; this mirrors the existing central
Twilio webhook contract.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from commerce_adapter.app.canonical_event import (
    InvalidTwilioForm,
    empty_twiml_response,
    normalize_twilio_form,
)
from commerce_adapter.app.config import CommerceAdapterConfig
from commerce_adapter.app.dependencies import (
    build_config_dependency,
)
from commerce_adapter.app.novaorders_client import (
    NovaOrdersUnreachable,
)
from commerce_adapter.app.novaorders_client import (
    forward_event as _default_forward_event,
)
from commerce_adapter.app.schemas import CanonicalInboundEvent
from commerce_adapter.app.security import (
    assert_validation_path_safe,
    build_twilio_validation_url,
    validate_twilio_signature,
)

logger = logging.getLogger(__name__)


ROUTE_PATH: str = "/webhooks/twilio/whatsapp/inbound"

router = APIRouter(tags=["twilio-webhook"])


async def read_full_form(request: Request) -> dict[str, str]:
    """Async dependency that reads the complete submitted Twilio form.

    The dependency returns only string values so the synchronous
    handler receives a plain ``dict[str, str]`` without ever needing
    ``await``. It performs zero downstream work of its own; signature
    validation, normalization and the NovaOrders forward happen in
    the synchronous handler.
    """
    form_pairs = await request.form()
    return {
        str(key): value
        for key, value in form_pairs.items()
        if isinstance(value, str)
    }


def _address_marker(value: str) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "short"
    return f"tail-{digits[-4:]}"


def _message_sid_marker(value: str) -> str:
    if not isinstance(value, str) or len(value) < 6:
        return "short"
    return f"tail-{value[-6:]}"


def _xml_response(body: str, status_code: int) -> Response:
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
    )


def _resolve_forward_event():
    return _default_forward_event


@router.post(ROUTE_PATH)
def post_twilio_whatsapp_inbound(
    request: Request,
    x_twilio_signature: str | None = Header(
        default=None, alias="X-Twilio-Signature"
    ),
    form: Mapping[str, str] = Depends(read_full_form),
    config: CommerceAdapterConfig = Depends(build_config_dependency),  # noqa: B008
    forward_event=Depends(_resolve_forward_event),  # noqa: B008
) -> Response:
    """Handle one Twilio WhatsApp inbound form request."""
    assert_validation_path_safe(ROUTE_PATH)
    base_url = config.twilio_webhook_base_url
    auth_token = config.twilio_auth_token

    url = build_twilio_validation_url(
        base_url=base_url,
        path=ROUTE_PATH,
        query_string=request.url.query,
    )

    form_dict: dict[str, str] = {
        str(key): value for key, value in form.items() if isinstance(value, str)
    }
    signature_valid = validate_twilio_signature(
        auth_token=auth_token,
        url=url,
        params=form_dict,
        signature=x_twilio_signature,
    )
    if not signature_valid:
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "status": "signature_rejected",
            },
        )
        return _xml_response("", 403)

    try:
        canonical = normalize_twilio_form(
            form_dict,
            instalacion_id=config.installation_id,
            comercio_id=0,
        )
    except InvalidTwilioForm:
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "status": "invalid_form",
            },
        )
        return _xml_response(empty_twiml_response(), 200)

    try:
        comercio_id = int(config.comercio_id)
    except (TypeError, ValueError) as exc:
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "status": "missing_comercio_id",
                "error": type(exc).__name__,
            },
        )
        return _xml_response(empty_twiml_response(), 200)

    event = CanonicalInboundEvent(
        instalacion_id=canonical.instalacion_id,
        comercio_id=comercio_id,
        proveedor=canonical.proveedor,
        message_sid=canonical.message_sid,
        from_e164=canonical.from_e164,
        to_e164=canonical.to_e164,
        cuerpo=canonical.cuerpo,
        profile_name_hash=canonical.profile_name_hash,
        num_media=canonical.num_media,
    )

    try:
        result = forward_event(config=config, event=event)
    except NovaOrdersUnreachable as exc:
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "message_sid": _message_sid_marker(canonical.message_sid),
                "status": "novaorders_unreachable",
                "error": type(exc).__name__,
            },
        )
        return _xml_response("", 502)

    if result.is_accepted:
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "message_sid": _message_sid_marker(canonical.message_sid),
                "comercio_id": event.comercio_id,
                "status": result.status,
            },
        )
        return _xml_response(empty_twiml_response(), 200)

    if result.status == "rejected":
        logger.info(
            "commerce_adapter_inbound_outcome",
            extra={
                "instalacion_id": config.installation_id,
                "message_sid": _message_sid_marker(canonical.message_sid),
                "comercio_id": event.comercio_id,
                "status": "rejected",
                "reason": result.reason or "unknown",
            },
        )
        return _xml_response(empty_twiml_response(), 200)

    logger.info(
        "commerce_adapter_inbound_outcome",
        extra={
            "instalacion_id": config.installation_id,
            "message_sid": _message_sid_marker(canonical.message_sid),
            "comercio_id": event.comercio_id,
            "status": "unreachable",
            "http_status": result.http_status,
        },
    )
    return _xml_response("", 502)


__all__ = [
    "ROUTE_PATH",
    "post_twilio_whatsapp_inbound",
    "read_full_form",
    "router",
]