"""Twilio SDK seam for the T-C adapter.

The adapter is the only component that calls
``twilio.rest.Client.messages.create``. The seam exposes a small
Protocol so tests can inject a fake without depending on the real SDK
or a real Twilio account.

The send function maps the SDK's typed result to the bounded
:class:`TwilioOutboundResult` so the route can branch on a typed
status without inspecting raw SDK payloads or exception text. Body,
phone, token, signature and raw exception text never appear in the
result.

The module also exposes a bounded HTTP-based client for the
``emulator`` provider mode. The emulator client honours the same
``create(**kwargs)`` contract so the outbound route does not need to
branch on the underlying transport. The emulator mode is opt-in: the
``real`` mode — which instantiates the pinned ``twilio.rest.Client`` —
remains the default and unchanged. The emulator client NEVER contacts
``api.twilio.com``.
"""
from __future__ import annotations

import base64
import enum
import json
from dataclasses import dataclass
from typing import Any, Protocol

from twilio.base.exceptions import TwilioRestException


class TwilioOutboundFailureCategory(str, enum.Enum):
    """Safe provider-failure classification.

    The values mirror the central adapter so the bounded CLI can
    translate the typed result into the existing outbox state without
    branching on provider-specific strings.
    """

    RETRYABLE_TIMEOUT = "retryable_timeout"
    RETRYABLE_429 = "retryable_429"
    RETRYABLE_5XX = "retryable_5xx"
    TERMINAL_4XX = "terminal_4xx"


class TwilioOutboundStatus(str, enum.Enum):
    SENT = "sent"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class TwilioOutboundResult:
    """Typed result of the bounded merchant Twilio send."""

    status: str
    message_sid: str | None = None
    code: str | None = None
    http_status: int = 0


class TwilioMessagesClient(Protocol):
    """Structural seam for ``twilio.rest.Client.messages``.

    The adapter only depends on the ``create(**kwargs)`` contract.
    Tests inject a stand-in; production code passes the SDK
    ``Client.messages`` instance.
    """

    def create(self, **kwargs: Any) -> Any: ...


_RETRYABLE_5XX: frozenset[int] = frozenset({408, 425, *range(500, 600)})


def _as_whatsapp_address(canonical_e164: str) -> str:
    return f"whatsapp:{canonical_e164}"


def _coerce_http_status(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_codigo(exc: TwilioRestException, status: int) -> str:
    raw_code = getattr(exc, "code", None)
    if isinstance(raw_code, bool):
        raw_code = None
    if isinstance(raw_code, int) and raw_code > 0:
        return str(int(raw_code))
    return str(int(status))


def _classify_rest_exception(exc: TwilioRestException) -> tuple[str, str | None, int | None]:
    status = _coerce_http_status(getattr(exc, "status", None))
    if status == 429:
        return (
            TwilioOutboundStatus.RETRYABLE.value,
            _safe_codigo(exc, status),
            status,
        )
    if status in _RETRYABLE_5XX:
        return (
            TwilioOutboundStatus.RETRYABLE.value,
            _safe_codigo(exc, status),
            status,
        )
    if status is not None:
        return (
            TwilioOutboundStatus.TERMINAL.value,
            _safe_codigo(exc, status),
            status,
        )
    raise exc


def send(
    client: TwilioMessagesClient,
    *,
    destinatario_e164: str,
    sender_e164: str,
    cuerpo: str,
    status_callback_url: str | None,
):
    """Send exactly one message through the supplied seam.

    Returns a typed result with ``status``,
    ``message_sid``/``code`` and ``http_status`` populated. Body,
    phone, token and raw exception text never appear in the result.

    ``status_callback_url`` is optional: when ``None`` the SDK call
    omits the kwarg so the dispatcher never invents a placeholder
    URL for production or staging.
    """
    try:
        create_kwargs: dict[str, Any] = {
            "to": _as_whatsapp_address(destinatario_e164),
            "from_": _as_whatsapp_address(sender_e164),
            "body": cuerpo,
        }
        if status_callback_url:
            create_kwargs["status_callback"] = str(status_callback_url)
        message = client.create(**create_kwargs)
    except TwilioRestException as exc:
        status, code, http_status = _classify_rest_exception(exc)
        return TwilioOutboundResult(
            status=status,
            message_sid=None,
            code=code,
            http_status=http_status if http_status is not None else 0,
        )

    sid = getattr(message, "sid", None)
    return TwilioOutboundResult(
        status=TwilioOutboundStatus.SENT.value,
        message_sid=str(sid) if sid is not None else None,
        code=None,
        http_status=0,
    )


class _EmulatorTransportError(Exception):
    """Bounded transport error raised by the emulator HTTP seam."""


class TwilioEmulatorMessagesClient:
    """Standalone HTTP-based Twilio Messages API client for emulator mode.

    The class honours the same ``create(**kwargs)`` contract as the
    pinned Twilio SDK ``Client.messages`` instance so the outbound
    route can keep using the documented seam. The client POSTs the
    bounded payload to ``<emulator_base_url>/2010-04-01/Accounts/<account_sid>/Messages.json``
    with HTTP Basic authentication using the generated emulator
    credentials.

    The class NEVER contacts ``api.twilio.com``. The base URL is the
    operator-pinned emulator URL; the class refuses to start without
    it. The credentials are passed verbatim to the emulator — the
    generated account SID and auth token are owned by the operator
    test configuration.
    """

    def __init__(
        self,
        *,
        base_url: str,
        account_sid: str,
        auth_token: str,
        timeout_seconds: float,
    ) -> None:
        from urllib.parse import urlparse

        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url is required")
        parsed = urlparse(base_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("emulator base_url must be an absolute https URL")
        if not isinstance(account_sid, str) or not account_sid.startswith("AC"):
            raise ValueError("emulator account_sid must be a canonical Twilio SID")
        if not isinstance(auth_token, str) or not auth_token:
            raise ValueError("emulator auth_token is required")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._base_url = base_url.rstrip("/")
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._timeout_seconds = float(timeout_seconds)
        self._last_message_sid: str | None = None
        self._last_http_status: int = 0
        self._last_payload: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        """POST the bounded message create payload to the emulator.

        The Twilio Messages API expects Twilio-shaped JSON field
        names (``To``, ``From``, ``Body``) — the bounded SDK seam
        receives Python-shaped kwargs (``to``, ``from_``, ``body``).
        The helper translates the Python kwargs to Twilio-shaped
        field names before POSTing the payload so the emulator
        validator accepts the call. Only the documented keys are
        forwarded: unknown kwargs are dropped to keep the surface
        bounded.
        """
        url = (
            f"{self._base_url}/2010-04-01/Accounts/"
            f"{self._account_sid}/Messages.json"
        )
        twilio_payload: dict[str, str] = {}
        if "to" in kwargs and kwargs["to"] is not None:
            twilio_payload["To"] = str(kwargs["to"])
        if "from_" in kwargs and kwargs["from_"] is not None:
            twilio_payload["From"] = str(kwargs["from_"])
        if "body" in kwargs and kwargs["body"] is not None:
            twilio_payload["Body"] = str(kwargs["body"])
        if kwargs.get("status_callback"):
            twilio_payload["StatusCallback"] = str(kwargs["status_callback"])
        body = json.dumps(twilio_payload, sort_keys=True, separators=(",", ":"))
        basic = base64.b64encode(
            f"{self._account_sid}:{self._auth_token}".encode()
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(url, content=body, headers=headers)
        except Exception as exc:
            raise _EmulatorTransportError(type(exc).__name__) from exc
        self._last_http_status = int(response.status_code)
        if response.status_code != 201:
            raise _EmulatorTransportError(
                f"emulator_http_status_{int(response.status_code)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise _EmulatorTransportError("invalid_payload") from exc
        self._last_payload = payload if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            raise _EmulatorTransportError("invalid_payload_shape")
        sid = payload.get("sid")
        self._last_message_sid = str(sid) if sid is not None else None
        return _EmulatorMessageResource(sid=self._last_message_sid, payload=payload)


class _EmulatorMessageResource:
    """Lightweight stand-in for ``twilio.rest.api.v2010.account.message.MessageInstance``.

    The outbound adapter only reads ``.sid``; the helper returns the
    value verbatim so the existing adapter code keeps working
    unchanged.
    """

    def __init__(self, *, sid: str | None, payload: dict[str, Any]) -> None:
        self.sid = sid
        self._payload = payload

    def __getattr__(self, name: str) -> Any:
        if name in {"sid", "_payload"}:
            raise AttributeError(name)
        return self._payload.get(name)


def send_emulator(
    client: TwilioEmulatorMessagesClient,
    *,
    destinatario_e164: str,
    sender_e164: str,
    cuerpo: str,
    status_callback_url: str | None,
):
    """Send one message through the emulator seam.

    The function mirrors :func:`send` so the route can branch on a
    typed status. A ``_EmulatorTransportError`` is translated into a
    retryable result; any other exception is re-raised so a future
    test can identify it.
    """
    try:
        create_kwargs: dict[str, Any] = {
            "to": _as_whatsapp_address(destinatario_e164),
            "from_": _as_whatsapp_address(sender_e164),
            "body": cuerpo,
        }
        if status_callback_url:
            create_kwargs["status_callback"] = str(status_callback_url)
        message = client.create(**create_kwargs)
    except _EmulatorTransportError as exc:
        return TwilioOutboundResult(
            status=TwilioOutboundStatus.RETRYABLE.value,
            message_sid=None,
            code=type(exc).__name__,
            http_status=int(getattr(client, "_last_http_status", 0)) or 0,
        )

    sid = getattr(message, "sid", None)
    return TwilioOutboundResult(
        status=TwilioOutboundStatus.SENT.value,
        message_sid=str(sid) if sid is not None else None,
        code=None,
        http_status=0,
    )


__all__ = [
    "TwilioEmulatorMessagesClient",
    "TwilioMessagesClient",
    "TwilioOutboundFailureCategory",
    "TwilioOutboundResult",
    "TwilioOutboundStatus",
    "send",
    "send_emulator",
]