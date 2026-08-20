"""Authenticated outbound command route for the T-C adapter.

The route is the only entry point that performs a real
``Client.messages.create`` call for this merchant. It accepts a
canonical outbound command, validates the HMAC signature against the
installation secret, validates the ``instalacion_id`` /
``comercio_id`` pair against the local configuration and dispatches
exactly one ``messages.create`` through the typed seam.

The route validates the full authentication envelope:

1. ``X-Installation-Id`` header is present and matches the local
   ``TC_INSTALLATION_ID`` configuration — the adapter never
   processes a command issued for another installation;
2. ``X-Installation-Signature`` header recomputes against the exact
   body bytes using the local installation secret;
3. ``instalacion_id`` from the JSON body matches the local
   configuration — the body field is re-resolved against the
   header;
4. ``comercio_id`` from the JSON body matches the local
   ``TC_COMERCIO_ID`` configuration — the body field is re-resolved
   against the adapter identity.

A mismatch on any of those four checks is a typed ``401`` /
``403`` and zero ``messages.create`` calls fire.

The route never logs body, phone, token, signature or credential. It
emits exactly one safe ``commerce_adapter_outbound_attempt`` log
record per accepted command.

The bounded CLI does not re-issue a command for the same
``idempotency_key``; the durable NovaOrders
``instalaciones_twilio_comercio_idempotencia`` table enforces exactly
one send per row.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from commerce_adapter.app.config import (
    PROVIDER_MODE_EMULATOR,
    CommerceAdapterConfig,
)
from commerce_adapter.app.dependencies import get_config
from commerce_adapter.app.schemas import CanonicalOutboundCommand
from commerce_adapter.app.security import hmac_verify
from commerce_adapter.app.twilio_client import (
    TwilioEmulatorMessagesClient,
    TwilioOutboundResult,
)
from commerce_adapter.app.twilio_client import (
    send as twilio_send,
)
from commerce_adapter.app.twilio_client import (
    send_emulator as twilio_send_emulator,
)

logger = logging.getLogger(__name__)


ROUTE_PATH: str = "/send-message"
SIGNATURE_HEADER: str = "X-Installation-Signature"
INSTALLATION_ID_HEADER: str = "X-Installation-Id"

router = APIRouter(prefix="/internal/commands", tags=["outbound-command"])


def _address_marker(value: str) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "short"
    return f"tail-{digits[-4:]}"


def _idempotency_marker(value: str) -> str:
    if not isinstance(value, str) or len(value) < 6:
        return "short"
    return f"tail-{value[-6:]}"


def _build_twilio_client(config: CommerceAdapterConfig):
    """Build the bounded Twilio SDK client.

    Production code returns ``Client(config.twilio_account_sid,
    config.twilio_auth_token).messages``. Tests inject a fake through
    :func:`set_twilio_client`. The function is only invoked in
    ``real`` provider mode; ``emulator`` mode never instantiates the
    real SDK.
    """
    from twilio.rest import Client

    return Client(config.twilio_account_sid, config.twilio_auth_token).messages


def _build_emulator_client(config: CommerceAdapterConfig):
    """Build the bounded Twilio emulator HTTP client.

    The function is only invoked in ``emulator`` provider mode and
    fails closed at construction time when the operator did not
    configure the emulator URL or the generated credentials. The
    client never contacts ``api.twilio.com``.
    """
    if (
        not config.twilio_emulator_base_url
        or not config.twilio_emulator_account_sid
        or not config.twilio_emulator_auth_token
    ):
        raise RuntimeError(
            "emulator provider mode is enabled but the emulator "
            "configuration is incomplete"
        )
    return TwilioEmulatorMessagesClient(
        base_url=config.twilio_emulator_base_url,
        account_sid=config.twilio_emulator_account_sid,
        auth_token=config.twilio_emulator_auth_token,
        timeout_seconds=float(config.http_timeout_seconds),
    )


_TWILIO_CLIENT_OVERRIDE: dict[str, Any] = {}


def set_twilio_client(client) -> None:
    _TWILIO_CLIENT_OVERRIDE["client"] = client


def _get_twilio_client(config: CommerceAdapterConfig):
    if "client" in _TWILIO_CLIENT_OVERRIDE:
        return _TWILIO_CLIENT_OVERRIDE["client"]
    if config.provider_mode == PROVIDER_MODE_EMULATOR:
        return _build_emulator_client(config)
    return _build_twilio_client(config)


@router.post(ROUTE_PATH)
async def send_message(
    request: Request,
    x_installation_signature: str | None = Header(
        default=None, alias=SIGNATURE_HEADER
    ),
    x_installation_id: str | None = Header(
        default=None, alias=INSTALLATION_ID_HEADER
    ),
    config: CommerceAdapterConfig = Depends(get_config),  # noqa: B008
) -> JSONResponse:
    """Perform exactly one merchant Twilio send.

    The route is async so the body is read without blocking the event
    loop. The route never logs body, phone, token or signature.

    Authentication is enforced in this exact order:

    1. ``X-Installation-Id`` header presence and exact match against
       the local ``TC_INSTALLATION_ID``;
    2. HMAC signature verification on the raw body bytes against the
       local installation secret;
    3. JSON body parsing against the canonical outbound schema;
    4. ``instalacion_id`` exact match between body and local config;
    5. ``comercio_id`` exact match between body and local config.

    Any failure returns a typed ``401`` / ``403`` and zero
    ``messages.create`` calls fire.
    """
    if not isinstance(x_installation_id, str) or not x_installation_id:
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "installation_id_header_missing",
            },
        )
        raise HTTPException(
            status_code=401,
            detail="X-Installation-Id header is missing",
        )
    if str(x_installation_id) != str(config.installation_id):
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "installation_id_header_mismatch",
            },
        )
        raise HTTPException(
            status_code=401,
            detail="X-Installation-Id does not match this installation",
        )

    body = await request.body()
    if not hmac_verify(
        payload=body,
        secret=config.installation_secret,
        presented=x_installation_signature,
    ):
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "signature_rejected",
            },
        )
        raise HTTPException(
            status_code=401,
            detail="installation signature is missing or invalid",
        )

    try:
        command = CanonicalOutboundCommand.model_validate_json(body)
    except ValidationError as exc:
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "invalid_payload",
            },
        )
        raise HTTPException(status_code=400, detail="invalid command payload") from exc

    if str(command.instalacion_id) != str(config.installation_id):
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "instalacion_id_mismatch",
            },
        )
        raise HTTPException(
            status_code=403,
            detail="command does not match this installation",
        )

    expected_comercio_id = int(config.comercio_id)
    if int(command.comercio_id) != int(expected_comercio_id):
        logger.info(
            "commerce_adapter_outbound_attempt",
            extra={
                "instalacion_id": config.installation_id,
                "status": "comercio_id_mismatch",
            },
        )
        raise HTTPException(
            status_code=403,
            detail="command does not match this installation",
        )

    sender_e164 = str(config.twilio_sender_e164)
    client = _get_twilio_client(config)
    callback_url = command.status_callback_url
    if config.provider_mode == PROVIDER_MODE_EMULATOR:
        result: TwilioOutboundResult = twilio_send_emulator(
            client,  # type: ignore[arg-type]
            destinatario_e164=str(command.destinatario_e164),
            sender_e164=sender_e164,
            cuerpo=str(command.cuerpo),
            status_callback_url=(
                str(callback_url) if callback_url else None
            ),
        )
    else:
        result = twilio_send(
            client,  # type: ignore[arg-type]
            destinatario_e164=str(command.destinatario_e164),
            sender_e164=sender_e164,
            cuerpo=str(command.cuerpo),
            status_callback_url=(
                str(callback_url) if callback_url else None
            ),
        )

    logger.info(
        "commerce_adapter_outbound_attempt",
        extra={
            "instalacion_id": config.installation_id,
            "comercio_id": int(command.comercio_id),
            "idempotency_key": _idempotency_marker(command.idempotency_key),
            "status": str(result.status),
            "provider_code": result.code,
            "http_status": int(result.http_status),
        },
    )

    payload = {
        "status": str(result.status),
        "message_sid": result.message_sid,
        "code": result.code,
    }
    return JSONResponse(status_code=200, content=payload)


def _resolve_local_sender_e164(config: CommerceAdapterConfig) -> str:
    return str(config.twilio_sender_e164)


def _resolve_local_comercio_id(config: CommerceAdapterConfig) -> int:
    return int(config.comercio_id)


__all__ = [
    "ROUTE_PATH",
    "SIGNATURE_HEADER",
    "router",
    "send_message",
    "set_twilio_client",
]