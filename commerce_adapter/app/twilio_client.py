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
"""
from __future__ import annotations

import enum
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


__all__ = [
    "TwilioMessagesClient",
    "TwilioOutboundFailureCategory",
    "TwilioOutboundResult",
    "TwilioOutboundStatus",
    "send",
]