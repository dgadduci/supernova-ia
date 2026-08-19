"""NovaOrders internal ingress for commerce-owned T-C adapters.

The router is the only HTTP entry point that accepts a canonical
inbound event from a T-C adapter. It is intentionally narrow:

1. A FastAPI dependency decrypts the per-installation envelope,
   recomputes the HMAC-SHA256 signature over the raw request bytes and
   rejects any request whose signature does not match.
2. The handler delegates to the existing
   :class:`ProviderInboundMessageCoordinator` exactly like the central
   Twilio webhook does; the coordinator remains the sole transaction
   owner for the receipt + deferred work pair.
3. The handler maps the coordinator outcome to the documented JSON
   response (``accepted`` / ``duplicate`` / ``rejected``). The T-C
   adapter translates every response into the same empty TwiML.

The router does not require the administrative token. It does not
inspect the Twilio form, does not parse Twilio signature headers and
does not call the classifier, recognizer, handler, response mapper or
outbox. It only forwards the canonical event and reports the durable
outcome of the bounded coordinator.

The router never logs the body, phone, token, signature or credential.
It only emits a single safe ``core_inbound_acceptance`` event carrying
``instalacion_id_tail``, ``comercio_id``, ``canal_id``,
``cliente_id``, ``receipt_id`` and the typed status.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session as DatabaseSession

from backend.dependencies import get_session
from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.repositories.canal_whatsapp_repository import CanalWhatsappRepository
from backend.repositories.cliente_repository import ClienteRepository
from backend.repositories.instalacion_twilio_comercio_repository import (
    InstalacionTwilioComercioRepository,
)
from backend.schemas.commerce_installation_event import (
    CanonicalInboundAcceptResponse,
    CanonicalInboundEvent,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.exceptions import (
    InvalidInstallationSecretEnvelope,
)
from backend.services.instalacion_secret_envelope import resolve_master_keys_from_env
from backend.services.instalacion_twilio_comercio_service import (
    InstalacionTwilioComercioService,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
)

logger = logging.getLogger(__name__)


INSTALLATION_SIGNATURE_HEADER: str = "X-Installation-Signature"
_ROUTE_PREFIX: str = "/internal/commerce-installation"
_ACCEPT_PATH: str = "/accept-event"


router = APIRouter(prefix=_ROUTE_PREFIX, tags=["internal-commerce-installation"])


def _address_marker(value: str) -> str:
    """Stable non-reversible log marker.

    Returns the trailing 4 digits of the canonical E.164 value (or the
    literal ``"unknown"`` / ``"short"`` sentinels) so the bounded log
    records can correlate the same customer across events without
    exposing the raw phone number.
    """
    if not isinstance(value, str) or not value:
        return "unknown"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "short"
    return f"tail-{digits[-4:]}"


def _instalacion_marker(instalacion_id: str) -> str:
    if not isinstance(instalacion_id, str) or len(instalacion_id) < 6:
        return "short"
    return f"tail-{instalacion_id[-6:]}"


def _expected_signature(*, body: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return digest


def _resolve_master_keys_or_raise():
    try:
        return resolve_master_keys_from_env()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="installation master key is not configured",
        ) from exc


async def _read_body(request: Request) -> bytes:
    """Read the raw request body exactly once so the HMAC verification
    sees the exact bytes the adapter signed.

    FastAPI caches the body on the request after ``await request.body()``
    so the downstream Pydantic validation reuses the same bytes.
    """
    return await request.body()


def _verify_signature_or_401(
    *, body: bytes, presented: str | None, secret: str
) -> None:
    if not isinstance(presented, str) or not presented:
        raise HTTPException(
            status_code=401,
            detail="installation signature is missing or malformed",
        )
    expected = _expected_signature(body=body, secret=secret)
    if not hmac.compare_digest(expected, presented):
        raise HTTPException(
            status_code=401,
            detail="installation signature mismatch",
        )


def _decode_payload(body: bytes) -> CanonicalInboundEvent:
    try:
        raw = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="canonical event payload is not valid JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail="canonical event payload must be a JSON object",
        )
    try:
        return CanonicalInboundEvent.model_validate(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="canonical event payload is invalid",
        ) from exc


@router.post(
    "/{instalacion_id}" + _ACCEPT_PATH,
    response_model=CanonicalInboundAcceptResponse,
)
async def accept_event(
    instalacion_id: str,
    request: Request,
    session: DatabaseSession = Depends(get_session),  # noqa: B008
    x_installation_signature: str | None = Header(
        default=None, alias=INSTALLATION_SIGNATURE_HEADER
    ),
) -> Response:
    """Accept one canonical inbound event from a T-C adapter.

    The dependency decrypts the per-installation envelope, recomputes
    the HMAC signature over the exact body bytes and rejects on
    mismatch. The handler delegates to the existing
    :class:`ProviderInboundMessageCoordinator` and maps the typed
    outcome to the documented JSON response.
    """
    body = await _read_body(request)
    bundle = _resolve_master_keys_or_raise()
    repo = InstalacionTwilioComercioRepository(session)
    row = repo.find_by_instalacion_id(instalacion_id)
    if row is None:
        raise HTTPException(
            status_code=401,
            detail="installation is not registered",
        )
    if not bool(row.activo):
        raise HTTPException(
            status_code=401,
            detail="installation is inactive",
        )

    try:
        decrypted = InstalacionTwilioComercioService(
            session=session, master_keys=bundle
        ).decrypt_installation_secret(instalacion_id)
    except InvalidInstallationSecretEnvelope as exc:
        raise HTTPException(
            status_code=502,
            detail="installation envelope cannot be decrypted",
        ) from exc

    if int(decrypted.comercio_id) != int(row.id_comercio):
        raise HTTPException(
            status_code=401,
            detail="installation envelope commerce mismatch",
        )

    _verify_signature_or_401(
        body=body,
        presented=x_installation_signature,
        secret=decrypted.plain_secret,
    )

    payload = _decode_payload(body)

    if str(payload.instalacion_id) != str(instalacion_id):
        raise HTTPException(
            status_code=400,
            detail="canonical event instalacion_id mismatch",
        )
    if int(payload.comercio_id) != int(row.id_comercio):
        raise HTTPException(
            status_code=400,
            detail="canonical event comercio_id mismatch",
        )

    canal_repo = CanalWhatsappRepository(session)
    canal = canal_repo.find_active_by_provider_destination(
        provider=str(payload.proveedor),
        destination_e164=str(payload.to_e164),
    )
    if canal is None:
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "status": "rejected",
                "reason": "unknown_destination",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="rejected", reason="unknown_destination"
            ).model_dump()
        )
    if canal.mode is not CanalWhatsappMode.DEDICATED:
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "status": "rejected",
                "reason": "shared_channel_not_supported",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="rejected", reason="shared_channel_not_supported"
            ).model_dump()
        )
    if (
        canal.id_comercio_exclusivo is None
        or int(canal.id_comercio_exclusivo) != int(row.id_comercio)
    ):
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "status": "rejected",
                "reason": "channel_commerce_mismatch",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="rejected", reason="channel_commerce_mismatch"
            ).model_dump()
        )

    cliente_repo = ClienteRepository(session)
    cliente = cliente_repo.get_by_whatsapp(str(payload.from_e164))
    if cliente is None or not bool(cliente.activo):
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "from_e164_hash": _address_marker(payload.from_e164),
                "status": "rejected",
                "reason": "unknown_client",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="rejected", reason="unknown_client"
            ).model_dump()
        )

    availability = CommerceAvailabilityService(session).evaluate(int(row.id_comercio))
    if availability.status is not CommerceAvailabilityStatus.AVAILABLE:
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "cliente_id": int(cliente.id),
                "status": "rejected",
                "reason": "unavailable_commerce",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="rejected", reason="unavailable_commerce"
            ).model_dump()
        )

    outcome = ProviderInboundMessageCoordinator(session).accept(
        ProviderInboundMessageCommand(
            proveedor=str(payload.proveedor),
            identificador_recepcion=str(payload.message_sid),
            canal_id=int(canal.id),
            cliente_id=int(cliente.id),
            comercio_id=int(row.id_comercio),
            mensaje=str(payload.cuerpo),
            destinatario_e164=str(payload.from_e164),
        )
    )

    if outcome.status is ProviderInboundMessageStatus.ACCEPTED:
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "cliente_id": int(cliente.id),
                "receipt_id": outcome.receipt_id,
                "status": "accepted",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(
                status="accepted",
                receipt_id=outcome.receipt_id,
            ).model_dump()
        )
    if outcome.status is ProviderInboundMessageStatus.ALREADY_PROCESSED:
        logger.info(
            "core_inbound_acceptance",
            extra={
                "instalacion_id": _instalacion_marker(instalacion_id),
                "comercio_id": int(row.id_comercio),
                "canal_id": int(canal.id),
                "cliente_id": int(cliente.id),
                "status": "duplicate",
            },
        )
        return _json_response(
            CanonicalInboundAcceptResponse(status="duplicate").model_dump()
        )

    logger.info(
        "core_inbound_acceptance",
        extra={
            "instalacion_id": _instalacion_marker(instalacion_id),
            "comercio_id": int(row.id_comercio),
            "canal_id": int(canal.id),
            "cliente_id": int(cliente.id),
            "status": "rejected",
            "reason": str(outcome.resolution_source or "invalid_context"),
        },
    )
    return _json_response(
        CanonicalInboundAcceptResponse(
            status="rejected",
            reason=str(outcome.resolution_source or "invalid_context"),
        ).model_dump()
    )


def _json_response(body: dict) -> Response:
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=200, content=body)


__all__ = [
    "INSTALLATION_SIGNATURE_HEADER",
    "accept_event",
    "router",
]