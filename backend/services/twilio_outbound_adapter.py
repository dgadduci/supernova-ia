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
    """

    destinatario_e164: str
    sender_e164: str
    cuerpo: str
    status_callback_url: str
    idempotency_key: str


@dataclass(frozen=True)
class TwilioSendResult:
    """Immutable Phase-5.6 adapter outcome.

    ``status`` is the single source of truth for branching. The
    other fields are only meaningful for the matching non-empty
    outcome. ``message_sid`` is only populated when ``status ==
    SENT``; ``categoria`` and ``codigo`` are only populated when
    ``status != SENT``. Raw SDK payload bytes never reach the result
    so observability surfaces cannot leak provider data.
    """

    status: TwilioSendStatus
    message_sid: str | None
    categoria: OutboundFailureCategory | None
    codigo: str | None
    detalle: str | None


class TwilioMessagesClient(Protocol):
    """Structural typing seam for ``twilio.rest.Client.messages``.

    The adapter only depends on the ``create(**kwargs)`` contract.
    Tests inject a stand-in; production code passes the SDK
    ``Client.messages`` instance.
    """

    def create(self, **kwargs: Any) -> Any: ...


_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


def build_send_request(
    payload: OutboundDispatchPayload,
    *,
    sender_e164: str,
    status_callback_url: str,
) -> TwilioSendRequest:
    """Translate the dispatcher's payload into the exact Twilio
    SDK payload.

    The ``idempotency_key`` is derived from the stable outbox row id
    so two parallel dispatchers cannot accidentally trigger two
    independent sends for the same row.
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
        message = client.create(
            to=request.destinatario_e164,
            from_=request.sender_e164,
            body=request.cuerpo,
            status_callback=request.status_callback_url,
        )
    except _TwilioTransportError as exc:
        return _retryable(exc, OutboundFailureCategory.RETRYABLE_TIMEOUT, "transport_error")
    except _TwilioAPIError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in _RETRYABLE_HTTP_CODES:
            if code == 429:
                categoria = OutboundFailureCategory.RETRYABLE_429
            else:
                categoria = OutboundFailureCategory.RETRYABLE_5XX
            return _retryable(exc, categoria, str(code))
        return _terminal(exc, OutboundFailureCategory.TERMINAL_4XX, str(code))

    sid = getattr(message, "sid", None)
    return TwilioSendResult(
        status=TwilioSendStatus.SENT,
        message_sid=str(sid) if sid is not None else None,
        categoria=None,
        codigo=None,
        detalle=None,
    )


def classify_failure(
    *,
    exc: BaseException,
    codigo: str,
    categoria: OutboundFailureCategory,
) -> TwilioSendResult:
    """Translate a transport or API failure into a typed result.

    The helper exists so the dispatcher can re-classify a failure
    raised outside the SDK seam (e.g. a timeout from a higher-level
    HTTP wrapper) without losing the typed ``OutboundFailureCategory``
    contract.
    """
    if categoria in {
        OutboundFailureCategory.RETRYABLE_TIMEOUT,
        OutboundFailureCategory.RETRYABLE_429,
        OutboundFailureCategory.RETRYABLE_5XX,
    }:
        return _retryable(exc, categoria, codigo)
    return _terminal(exc, categoria, codigo)


def _retryable(
    exc: BaseException,
    categoria: OutboundFailureCategory,
    codigo: str,
) -> TwilioSendResult:
    return TwilioSendResult(
        status=TwilioSendStatus.RETRYABLE,
        message_sid=None,
        categoria=categoria,
        codigo=codigo,
        detalle=_safe_detail(exc),
    )


def _terminal(
    exc: BaseException,
    categoria: OutboundFailureCategory,
    codigo: str,
) -> TwilioSendResult:
    return TwilioSendResult(
        status=TwilioSendStatus.TERMINAL,
        message_sid=None,
        categoria=categoria,
        codigo=codigo,
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


class _TwilioAPIError(Exception):
    """Marker raised by the seam for Twilio API errors."""

    def __init__(self, code: int) -> None:
        super().__init__(f"twilio_api_error:{code}")
        self.code = int(code)


__all__ = [
    "TwilioMessagesClient",
    "TwilioSendRequest",
    "TwilioSendResult",
    "TwilioSendStatus",
    "build_send_request",
    "classify_failure",
    "send",
]