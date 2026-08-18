"""FastAPI boundary for the abuse guard service.

The module exposes:

* ``POST /check`` — the authoritative anti-abuse decision for the
  magic-link request;
* ``GET /health`` — bounded liveness response;
* ``GET /ready`` — bounded readiness response that exercises Redis.

The HTTP boundary is intentionally generic: it never echoes the
token, the hashed keys, the Redis URL or the request body. Logs are
bounded to event names and reason categories. The service never
imports from ``backend`` or any NovaOrders module.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from abuse_guard.config import (
    ConfigError,
    GuardConfig,
    is_valid_email,
    load_config,
)
from abuse_guard.limiter import (
    ACCEPTED_ACTION,
    LimiterError,
    RedisLimiter,
    RedisProtocol,
    ping,
)

logger = logging.getLogger("abuse_guard")

EVENT_ALLOWED = "guard_allowed"
EVENT_DENIED_RATE = "guard_denied_rate"
EVENT_AUTH_REJECTED = "guard_auth_rejected"
EVENT_INVALID_REQUEST = "guard_invalid_request"
EVENT_REDIS_UNAVAILABLE = "guard_redis_unavailable"
EVENT_NOT_READY = "guard_not_ready"
EVENT_CONFIG_INVALID = "guard_config_invalid"

DECISION_ID_BYTES = 18


def _emit_event(event: str, **fields: Any) -> None:
    """Emit a bounded log event without raw identifiers.

    Only the event name and the explicitly passed ``fields`` are
    included. The caller must never pass raw email, IP, tokens, Redis
    URLs or full request bodies.
    """

    extras = {key: value for key, value in fields.items() if value is not None}
    logger.info("event=%s %s", event, " ".join(f"{k}={v}" for k, v in extras.items()))


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "unauthorized"},
    )


def _forbidden() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": "forbidden"},
    )


def _bad_request(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": "invalid_request"},
        headers={"X-Reason-Category": reason} if reason else None,
    )


def _service_unavailable(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "service_unavailable"},
        headers={"X-Reason-Category": reason} if reason else None,
    )


def _new_decision_id() -> str:
    """Return a fresh opaque decision identifier.

    The identifier is a random URL-safe token and has no relationship
    to the email, IP, hash secret or any other request input.
    """

    return secrets.token_urlsafe(DECISION_ID_BYTES)


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not isinstance(header, str):
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    if not token:
        return None
    return token


def hmac_compare(provided: str, expected: str) -> bool:
    """Constant-time string comparison helper."""

    import hmac

    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _matches_token(provided: str, expected: str) -> bool:
    """Compare ``provided`` against ``expected`` without timing leak."""

    return hmac_compare(provided, expected)


def _build_decision_response(allowed: bool) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "allowed": allowed,
            "decision_id": _new_decision_id(),
        },
    )


async def _parse_json_body(request: Request) -> Mapping[str, Any] | None:
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _validate_payload(payload: Mapping[str, Any]) -> tuple[str, str | None] | None:
    action = payload.get("action")
    email = payload.get("email")
    if not isinstance(action, str) or action != ACCEPTED_ACTION:
        return None
    if not is_valid_email(email):
        return None
    remote_ip: str | None = None
    if "remote_ip" in payload:
        raw_ip = payload.get("remote_ip")
        if raw_ip is not None and not isinstance(raw_ip, str):
            return None
        if isinstance(raw_ip, str):
            stripped = raw_ip.strip()
            if stripped:
                remote_ip = stripped
    return str(email), remote_ip


def create_app(
    *,
    config: GuardConfig | None = None,
    redis_client: RedisProtocol | None = None,
    config_loader: Any = load_config,
) -> FastAPI:
    """Build the FastAPI application with the injected dependencies.

    Production callers fall back to defaults driven by
    :func:`load_config` and a real Redis client created from
    ``REDIS_URL``. Tests inject a fake Redis client and a fixed
    configuration.
    """

    resolved_config = config  # type: ignore[assignment]
    if resolved_config is None:
        try:
            resolved_config = config_loader()
        except (ConfigError, ValueError, TypeError) as exc:
            _emit_event(
                EVENT_CONFIG_INVALID,
                code=getattr(exc, "code", "config_invalid"),
            )
            resolved_config = None

    resolved_client: RedisProtocol | None = redis_client  # type: ignore[assignment]

    app = FastAPI(
        title="abuse_guard",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={"status": "ok"},
        )

    @app.get("/ready")
    async def ready() -> JSONResponse:
        if resolved_config is None:
            _emit_event(EVENT_NOT_READY, reason="config_invalid")
            return _service_unavailable("config_invalid")
        if resolved_client is None:
            _emit_event(EVENT_NOT_READY, reason="redis_missing")
            return _service_unavailable("redis_missing")
        try:
            healthy = ping(resolved_client)
        except LimiterError as exc:
            _emit_event(EVENT_REDIS_UNAVAILABLE, reason=exc.code)
            return _service_unavailable("redis_unavailable")
        if not healthy:
            _emit_event(EVENT_NOT_READY, reason="redis_unavailable")
            return _service_unavailable("redis_unavailable")
        return JSONResponse(
            status_code=200,
            content={"status": "ready"},
        )

    @app.post("/check")
    async def check(request: Request) -> Response:
        if resolved_config is None or resolved_client is None:
            _emit_event(EVENT_NOT_READY, reason="config_invalid")
            return _service_unavailable("config_invalid")

        token = _extract_bearer(request)
        if token is None:
            _emit_event(EVENT_AUTH_REJECTED, reason="missing_token")
            return _unauthorized()
        if not _matches_token(token, resolved_config.bearer_token):
            _emit_event(EVENT_AUTH_REJECTED, reason="invalid_token")
            return _forbidden()

        payload = await _parse_json_body(request)
        if payload is None:
            _emit_event(EVENT_INVALID_REQUEST, reason="malformed_body")
            return _bad_request("malformed_body")
        validated = _validate_payload(payload)
        if validated is None:
            _emit_event(EVENT_INVALID_REQUEST, reason="invalid_payload")
            return _bad_request("invalid_payload")
        raw_email, remote_ip = validated

        limiter = RedisLimiter(
            client=resolved_client,
            config=resolved_config,
        )
        try:
            outcome = limiter.check(raw_email=raw_email, raw_ip=remote_ip)
        except LimiterError as exc:
            _emit_event(EVENT_REDIS_UNAVAILABLE, reason=exc.code)
            return _service_unavailable("redis_unavailable")

        if outcome.allowed:
            _emit_event(EVENT_ALLOWED)
        else:
            _emit_event(EVENT_DENIED_RATE, dimension=outcome.reason)
        return _build_decision_response(outcome.allowed)

    return app


def build_runtime_redis_client(url: str) -> RedisProtocol:
    """Build a real Redis client from ``url``.

    Imports are deferred until invoked so the module can be imported
    during tests without Redis available.
    """

    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(url, decode_responses=False)


app = create_app(
    redis_client=None,
)


__all__ = [
    "EVENT_ALLOWED",
    "EVENT_AUTH_REJECTED",
    "EVENT_CONFIG_INVALID",
    "EVENT_DENIED_RATE",
    "EVENT_INVALID_REQUEST",
    "EVENT_NOT_READY",
    "EVENT_REDIS_UNAVAILABLE",
    "build_runtime_redis_client",
    "create_app",
    "hmac_compare",
]
