"""Phase-5.6 Twilio outbound REST adapter.

The adapter is the only place in the project that knows how to
convert one claimed outbound row into a Twilio REST API request. It
performs three responsibilities:

1. ``build_send_request`` — translates the dispatcher's typed
   ``OutboundDispatchPayload`` and a configured sender into the
   exact Twilio message-create call shape, with the configured
   absolute HTTPS ``status_callback`` URL.
2. ``send`` — invokes the Twilio SDK ``Client.messages.create``
   equivalent through a typed seam so tests can inject a stand-in
   without depending on the real SDK or a real token.
3. ``classify_failure`` — translates the SDK / transport error
   envelope into a safe ``OutboundFailureCategory`` and a sanitized
   ``codigo`` / ``detalle`` pair so the dispatcher can branch on
   retry / terminal decisions without logging raw SDK payloads.

The adapter is fully decoupled from the database layer: it does not
import the repository, the SQLAlchemy models, the coordinator, the
resolver, the response orchestrator or any FastAPI surface. It
MUST NOT call ``commit`` / ``rollback`` / ``begin`` / ``flush`` /
``close`` / ``expire`` / ``refresh`` or any SQLAlchemy
transaction-control method.

The adapter accepts a ``TwilioMessagesClient`` seam so focused tests
can substitute a stand-in; production code passes
``twilio.rest.Client(account_sid, auth_token).messages``.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Protocol

from twilio.base.exceptions import TwilioRestException


class OutboundFailureCategory(str, enum.Enum):
    """Safe provider-failure classification.

    The category is the only durable identifier of a transient or
    definitive provider failure. Raw provider payload bytes never
    reach this layer. ``RETRYABLE_TIMEOUT``, ``RETRYABLE_429`` and
    ``RETRYABLE_5XX`` are bounded by configuration;
    ``TERMINAL_4XX`` stops the row immediately. ``BUDGET_EXHAUSTED``
    is terminal and is set by the dispatcher when the configured
    maximum attempt count is reached without success.
    """

    RETRYABLE_TIMEOUT = "retryable_timeout"
    RETRYABLE_429 = "retryable_429"
    RETRYABLE_5XX = "retryable_5xx"
    TERMINAL_4XX = "terminal_4xx"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TwilioSendStatus(str, enum.Enum):
    """Typed outcomes returned by ``TwilioOutboundAdapter.send``.

    The dispatcher branches on ``status`` after a single ``send`` call
    so each attempt is observable end-to-end. The adapter never
    raises a business signal.
    """

    SENT = "sent"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class OutboundDispatchPayload:
    """Immutable dispatcher-side payload handed to the adapter.

    The adapter never touches the database, so it accepts the
    already-projected values it needs (destination, body and a
    stable idempotency tag) instead of the ORM row.
    """

    destinatario_e164: str
    cuerpo: str
    idempotency_key: str


@dataclass(frozen=True)
class TwilioSendRequest:
    """Immutable payload consumed by ``send``.

    Every field is the exact value the Twilio SDK requires. No
    secrets, no raw provider bodies and no internal ids are present.

    ``status_callback_url`` is optional: when ``None`` the SDK call
    omits the kwarg so the dispatcher never invents a placeholder
    URL for production or staging.
    """

    destinatario_e164: str
    sender_e164: str
    cuerpo: str
    status_callback_url: str | None
    idempotency_key: str


@dataclass(frozen=True)
class TwilioSendResult:
    """Immutable Phase-5.6 adapter outcome.

    ``status`` is the single source of truth for branching. The
    other fields are only meaningful for the matching non-empty
    outcome. ``message_sid`` is only populated when ``status ==
    SENT``; ``categoria``, ``codigo`` and ``http_status`` are only
    populated when ``status != SENT`` and the SDK exposed a safe
    REST status. Raw SDK payload bytes never reach the result so
    observability surfaces cannot leak provider data.
    """

    status: TwilioSendStatus
    message_sid: str | None
    categoria: OutboundFailureCategory | None
    codigo: str | None
    http_status: int | None
    detalle: str | None


class TwilioMessagesClient(Protocol):
    """Structural typing seam for ``twilio.rest.Client.messages``.

    The adapter only depends on the ``create(**kwargs)`` contract.
    Tests inject a stand-in; production code passes the SDK
    ``Client.messages`` instance.
    """

    def create(self, **kwargs: Any) -> Any: ...


_RETRYABLE_HTTP_STATUSES_5XX: frozenset[int] = frozenset({408, 425, *range(500, 600)})

_WHATSAPP_CHANNEL_PREFIX: str = "whatsapp:"


def _as_whatsapp_address(canonical_e164: str) -> str:
    """Render canonical ``+E.164`` as a Twilio WhatsApp channel address.

    The adapter is the only place in the project that knows the
    Twilio WhatsApp wire representation is ``whatsapp:+E.164``. Stored
    rows, the configured sender, routing values and inbound
    normalization remain canonical bare E.164; this helper applies
    the prefix immediately before the SDK call.

    The helper does not normalize an already-prefixed value — that
    would mix provider transport representation into an internal
    canonical contract and hide a caller/configuration defect.
    Existing validation remains the authority for canonical shape.
    """
    return f"{_WHATSAPP_CHANNEL_PREFIX}{canonical_e164}"


def build_send_request(
    payload: OutboundDispatchPayload,
    *,
    sender_e164: str,
    status_callback_url: str | None,
) -> TwilioSendRequest:
    """Translate the dispatcher's payload into the exact Twilio
    SDK payload.

    The ``idempotency_key`` is derived from the stable outbox row id
    so two parallel dispatchers cannot accidentally trigger two
    independent sends for the same row.

    ``status_callback_url`` is optional: when ``None`` the SDK call
    omits the kwarg so the dispatcher never invents a placeholder
    URL for production or staging.
    """
    return TwilioSendRequest(
        destinatario_e164=payload.destinatario_e164,
        sender_e164=sender_e164,
        cuerpo=payload.cuerpo,
        status_callback_url=status_callback_url,
        idempotency_key=payload.idempotency_key,
    )


def send(
    client: TwilioMessagesClient,
    request: TwilioSendRequest,
) -> TwilioSendResult:
    """Send one message through the supplied seam.

    The function performs the network call outside any database
    transaction: the dispatcher owns the claim transaction. A late
    network result cannot mutate a stale lease because the
    repository's finalization primitives check the lease token.
    """
    try:
        create_kwargs: dict[str, Any] = {
            "to": _as_whatsapp_address(request.destinatario_e164),
            "from_": _as_whatsapp_address(request.sender_e164),
            "body": request.cuerpo,
        }
        if request.status_callback_url:
            create_kwargs["status_callback"] = str(
                request.status_callback_url
            )
        message = client.create(**create_kwargs)
    except _TwilioTransportError as exc:
        return _retryable(exc, OutboundFailureCategory.RETRYABLE_TIMEOUT, "transport_error")
    except TwilioRestException as exc:
        return _classify_rest_exception(exc)

    sid = getattr(message, "sid", None)
    return TwilioSendResult(
        status=TwilioSendStatus.SENT,
        message_sid=str(sid) if sid is not None else None,
        categoria=None,
        codigo=None,
        http_status=None,
        detalle=None,
    )


def classify_failure(
    *,
    exc: BaseException,
    codigo: str,
    categoria: OutboundFailureCategory,
    http_status: int | None = None,
) -> TwilioSendResult:
    """Translate a transport or API failure into a typed result.

    The helper exists so the dispatcher can re-classify a failure
    raised outside the SDK seam (e.g. a timeout from a higher-level
    HTTP wrapper) without losing the typed ``OutboundFailureCategory``
    contract. ``http_status`` is preserved verbatim when known so
    the dispatcher can surface the Twilio HTTP classification
    alongside the safe provider code; the value never reaches the
    retry policy.
    """
    if categoria in {
        OutboundFailureCategory.RETRYABLE_TIMEOUT,
        OutboundFailureCategory.RETRYABLE_429,
        OutboundFailureCategory.RETRYABLE_5XX,
    }:
        return _retryable(exc, categoria, codigo, http_status=http_status)
    return _terminal(exc, categoria, codigo, http_status=http_status)


def _classify_rest_exception(exc: TwilioRestException) -> TwilioSendResult:
    """Translate the pinned SDK's ``TwilioRestException`` into a typed result.

    Retry classification uses the exception's HTTP ``status``. The
    Twilio provider ``code`` (when numeric) is carried only as the
    sanitized ``codigo`` field — it is observability data, never the
    retry policy driver. ``msg``, ``uri``, ``details`` and the raw
    ``str(exc)`` are never included in any result or log.

    If the HTTP ``status`` cannot be coerced to an integer, the
    exception is re-raised unchanged so an unexpected SDK state stays
    a technical failure rather than being silently misclassified.
    """
    status = _coerce_http_status(getattr(exc, "status", None))
    if status == 429:
        return _retryable(
            exc,
            OutboundFailureCategory.RETRYABLE_429,
            _safe_codigo(exc, status),
            http_status=status,
        )
    if status in _RETRYABLE_HTTP_STATUSES_5XX:
        return _retryable(
            exc,
            OutboundFailureCategory.RETRYABLE_5XX,
            _safe_codigo(exc, status),
            http_status=status,
        )
    if status is not None:
        return _terminal(
            exc,
            OutboundFailureCategory.TERMINAL_4XX,
            _safe_codigo(exc, status),
            http_status=status,
        )
    raise exc


def _coerce_http_status(value: Any) -> int | None:
    """Defensively coerce ``TwilioRestException.status`` to ``int``.

    The pinned ``twilio==9.10.9`` SDK declares ``status`` as a required
    ``int`` in ``TwilioRestException.__init__``. This helper protects
    the adapter against a future SDK change without silently
    misclassifying unknown states — unparseable values become
    ``None`` so the caller can re-raise the original exception.
    """
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
    """Pick a non-sensitive observability code for the result.

    The numeric Twilio provider error code (e.g. ``20003``) is
    preferred when present — it is the only Twilio-specific
    identifier the result exposes. When the provider omits ``code``
    we fall back to the HTTP status, which is also safe and never
    includes exception text.
    """
    raw_code = getattr(exc, "code", None)
    if isinstance(raw_code, bool):
        raw_code = None
    if isinstance(raw_code, int) and raw_code > 0:
        return str(int(raw_code))
    return str(int(status))


def _retryable(
    exc: BaseException,
    categoria: OutboundFailureCategory,
    codigo: str,
    *,
    http_status: int | None = None,
) -> TwilioSendResult:
    return TwilioSendResult(
        status=TwilioSendStatus.RETRYABLE,
        message_sid=None,
        categoria=categoria,
        codigo=codigo,
        http_status=http_status,
        detalle=_safe_detail(exc),
    )


def _terminal(
    exc: BaseException,
    categoria: OutboundFailureCategory,
    codigo: str,
    *,
    http_status: int | None = None,
) -> TwilioSendResult:
    return TwilioSendResult(
        status=TwilioSendStatus.TERMINAL,
        message_sid=None,
        categoria=categoria,
        codigo=codigo,
        http_status=http_status,
        detalle=_safe_detail(exc),
    )


def _safe_detail(exc: BaseException) -> str:
    """Return a non-sensitive single-line description.

    The detail is logged by the dispatcher; the body, signature and
    raw provider payload must never appear. The function returns
    ``type(exc).__name__`` only.
    """
    return type(exc).__name__


class _TwilioTransportError(Exception):
    """Marker raised by the seam for transport-level errors."""


__all__ = [
    "TwilioMessagesClient",
    "TwilioSendRequest",
    "TwilioSendResult",
    "TwilioSendStatus",
    "build_send_request",
    "classify_failure",
    "send",
]