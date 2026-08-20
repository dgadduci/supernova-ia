"""FastAPI application factory for the twilio emulator.

The module owns the application instance, the lifespan and the
narrow HTTP surfaces required by the approved change:

* a server-to-server authenticated inbound control surface that
  accepts the bounded command from the admin/pilot server and POSTs
  the signed Twilio form to the configured T-C webhook;
* a Twilio-shaped outbound Messages API that validates the basic
  auth credentials, records the bounded capture and returns a
  synthetic ``SM...`` identifier;
* a small health endpoint that returns the non-secret configuration
  projection so the operator can confirm the emulator is up.

The module never logs the control token, the auth token, the
signature, the URL, the inbound body, the outbound body, the
operator-supplied form values or any other sensitive value. The
emitter only carries the closed outcome vocabulary used by the
bounded observer.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse, Response

from twilio_emulator.captures import InMemoryCaptureStore
from twilio_emulator.config import (
    EmulatorConfig,
    load_config_from_env,
)
from twilio_emulator.service import (
    EmulatorAuthError,
    EmulatorUnavailable,
    EmulatorValidationError,
    InboundControlCommand,
    build_emulator_service,
    build_outbound_response_body,
)

logger = logging.getLogger(__name__)


_CONTROL_TOKEN_HEADER: str = "X-Emulator-Token"
_CONTROL_BODY_MAX_BYTES: int = 16 * 1024
_OUTBOUND_BODY_MAX_BYTES: int = 16 * 1024
_CAPTURE_INSPECTION_HEADER: str = "X-Emulator-Token"


def _http_post(url: str, *, form: dict[str, str], signature: str) -> None:
    """Post the signed form to the configured T-C webhook.

    The default ``http_post`` uses :class:`httpx.Client` so the
    emulator can run as a standalone process. Tests pass an
    in-memory replacement through :func:`create_app`.

    Only a 2xx HTTP response is considered a successful delivery:
    any other status (4xx, 5xx, timeout, network failure) raises
    :class:`EmulatorUnavailable` so the inbound control surface can
    return a bounded ``502`` and never report ``accepted`` to the
    admin caller. The function never logs the response body, the
    response headers or the URL so the structured log lines stay
    safe.
    """
    import httpx

    headers = {
        "X-Twilio-Signature": signature,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "twilio-emulator/0.1.0",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, data=form, headers=headers)
    except Exception as exc:
        raise EmulatorUnavailable(
            "t-c webhook is unreachable"
        ) from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise EmulatorUnavailable(
            "t-c webhook did not accept the signed form"
        )


def _basic_auth_decode(
    header_value: str | None,
) -> tuple[str | None, str | None]:
    if not isinstance(header_value, str) or not header_value:
        return None, None
    cleaned = header_value.strip()
    if not cleaned.lower().startswith("basic "):
        return None, None
    encoded = cleaned.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, binascii.Error):
        return None, None
    raw = decoded.decode("utf-8", errors="replace")
    if ":" not in raw:
        return None, None
    account_sid, _, auth_token = raw.partition(":")
    return account_sid, auth_token


def _default_capture_store(config: EmulatorConfig) -> InMemoryCaptureStore:
    return InMemoryCaptureStore(capture_retention=config.capture_retention)


async def _read_bounded_json(
    request: Request, *, max_bytes: int
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="payload too large",
        )
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload is required",
        )
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload is not valid JSON",
        ) from None
    if not isinstance(decoded, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload must be a JSON object",
        )
    return decoded


def _build_health_payload(config: EmulatorConfig) -> dict[str, Any]:
    return {
        "status": "ok",
        "emulator": config.to_public_dict(),
    }


def _build_inbound_response(
    *, message_sid: str, synthetic_inbound_id: str
) -> dict[str, Any]:
    return {
        "status": "accepted",
        "message_sid": message_sid,
        "synthetic_inbound_id": synthetic_inbound_id,
        "provider": "twilio-emulator",
    }


def create_app(
    *,
    config: EmulatorConfig | None = None,
    http_post: Any = None,
    captures: InMemoryCaptureStore | None = None,
) -> FastAPI:
    """Build the FastAPI emulator app.

    When ``config`` is ``None`` the function loads the configuration
    from environment variables at construction time. A missing or
    malformed value raises :class:`EmulatorConfigError` so the
    process refuses to start before the first request is served.
    """
    if config is None:
        config = load_config_from_env()
    if http_post is None:
        http_post = _http_post

    app = FastAPI(title="twilio-emulator", version="0.1.0")
    if captures is None:
        captures = _default_capture_store(config)
    service = build_emulator_service(
        config=config, http_post=http_post, captures=captures
    )
    app.state.emulator_service = service

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=_build_health_payload(config),
        )

    @app.get("/internal/emulator/captures")
    def inspect_captures(
        presented_token: str | None = Header(
            default=None, alias=_CAPTURE_INSPECTION_HEADER
        ),
    ) -> JSONResponse:
        if (
            not isinstance(presented_token, str)
            or presented_token != config.control_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="control token is missing or invalid",
            )
        snapshot = service.captures.snapshot()
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "retention": int(service.captures.retention),
                "captures": [
                    {
                        "message_sid": capture.message_sid,
                        "captured_at": capture.captured_at,
                        "to_address": capture.to_address,
                        "from_address": capture.from_address,
                    }
                    for capture in snapshot
                ],
            },
        )

    @app.post("/internal/emulator/inbound")
    async def inbound_control(
        request: Request,
        presented_token: str | None = Header(
            default=None, alias=_CONTROL_TOKEN_HEADER
        ),
    ) -> JSONResponse:
        payload = await _read_bounded_json(
            request, max_bytes=_CONTROL_BODY_MAX_BYTES
        )
        try:
            command = InboundControlCommand(
                source_e164=str(payload.get("source_e164", "")),
                destination_e164=str(payload.get("destination_e164", "")),
                body=str(payload.get("body", "")),
                synthetic_message_sid=(
                    str(payload["synthetic_message_sid"])
                    if "synthetic_message_sid" in payload
                    and isinstance(payload["synthetic_message_sid"], str)
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="inbound control payload is malformed",
            ) from exc
        try:
            result = await asyncio.to_thread(
                service.submit_inbound,
                presented_token=presented_token,
                command=command,
            )
        except EmulatorAuthError:
            logger.info(
                "twilio_emulator_inbound_rejected",
                extra={"status": "rejected", "reason": "auth"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="control token is missing or invalid",
            ) from None
        except EmulatorValidationError as exc:
            logger.info(
                "twilio_emulator_inbound_rejected",
                extra={"status": "rejected", "reason": "invalid"},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except EmulatorUnavailable:
            logger.info(
                "twilio_emulator_inbound_unreachable",
                extra={"status": "unreachable", "reason": "transport"},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="t-c webhook is unreachable",
            ) from None

        logger.info(
            "twilio_emulator_inbound_accepted",
            extra={"status": "accepted"},
        )
        return JSONResponse(
            status_code=200,
            content=_build_inbound_response(
                message_sid=result.message_sid,
                synthetic_inbound_id=result.message_sid,
            ),
        )

    @app.post("/2010-04-01/Accounts/{account_sid}/Messages.json")
    async def outbound_messages(
        account_sid: str,
        request: Request,
        authorization: str | None = Header(
            default=None, alias="Authorization"
        ),
    ) -> Response:
        presented_sid, presented_token = _basic_auth_decode(authorization)
        body = await _read_bounded_json(
            request, max_bytes=_OUTBOUND_BODY_MAX_BYTES
        )
        try:
            acceptance = await asyncio.to_thread(
                service.accept_outbound,
                account_sid=presented_sid or account_sid,
                presented_auth_token=presented_token,
                to_address=str(body.get("To", "")) or None,
                from_address=str(body.get("From", "")) or None,
            )
        except EmulatorAuthError as exc:
            logger.info(
                "twilio_emulator_outbound_rejected",
                extra={"status": "rejected", "reason": "auth"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from None
        except EmulatorValidationError as exc:
            logger.info(
                "twilio_emulator_outbound_rejected",
                extra={"status": "rejected", "reason": "invalid"},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from None

        payload = build_outbound_response_body(acceptance)
        return Response(
            content=payload,
            status_code=201,
            media_type="application/json; charset=utf-8",
        )

    return app


__all__ = [
    "_CONTROL_TOKEN_HEADER",
    "create_app",
]