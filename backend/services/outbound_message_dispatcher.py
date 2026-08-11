"""Phase-5.6 outbound message dispatcher.

The dispatcher is the only component in Phase 5.6 that drives the
outbox row state machine forward through the Twilio REST adapter. It
performs three responsibilities:

1. ``dispatch`` — claim one due pending/retryable row, send it
   through the configured Twilio adapter seam, and finalize the row
   in a single narrow transaction.
2. ``run_retry_pass`` — repeatedly claim and dispatch any due rows
   (bounded by ``max_attempts_per_pass`` so the operator entry point
   cannot starve). Each iteration is independent and only claims a
   row when one is due.
3. ``compute_next_attempt_at`` — deterministic bounded backoff so
   focused tests can predict the next-attempt timestamp without
   relying on jitter.

The dispatcher never imports HTTP, FastAPI, the Twilio SDK, the
coordinator, the resolver, the response orchestrator, the callback
service or the inbound webhook. It talks only to the outbox
repository and the adapter.

Transaction ownership is explicit and each narrow transaction is
opened and closed inside the dispatcher:

* the claim runs in its own short-lived session: the dispatcher
  opens the session, asks the repository to claim a single row,
  commits the lease and closes the session so the network call
  happens outside any database transaction;
* the Twilio adapter call happens between the claim commit and the
  finalize transaction — no SQLAlchemy session is open while the
  network round-trip is in flight;
* the finalization (``accepted`` / ``retryable`` / ``failed_terminal``)
  runs in a second short-lived session: the dispatcher opens the
  session, asks the repository to finalize the row, commits the
  result and closes the session.

The dispatcher receives a ``session_factory`` callable that yields a
new ``Session`` per call; the factory is the single boundary for
database access so production code wires a SQLAlchemy ``sessionmaker``
and tests can wire either a factory returning a mock or a real engine.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SqlSession

from backend.config.settings import Settings, load_settings
from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundFailureCategory,
)
from backend.observability import (
    COMPONENT_DATABASE,
    COMPONENT_OUTBOUND,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    EVENT_OUTBOUND_OUTCOME,
    categorize_sqlalchemy_error,
    emit_event,
)
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.services.outbound_dispatch_types import (
    OutboundAttemptEvent,
    OutboundAttemptOutcome,
    OutboundDispatchOutcome,
    OutboundDispatchResult,
    OutboundPassEvidence,
)
from backend.services.twilio_outbound_adapter import (
    OutboundDispatchPayload,
    TwilioMessagesClient,
    TwilioSendResult,
    TwilioSendStatus,
    build_send_request,
)
from backend.services.twilio_outbound_adapter import (
    OutboundFailureCategory as AdapterFailureCategory,
)
from backend.services.twilio_outbound_adapter import (
    send as twilio_send,
)


def _to_model_category(
    value: AdapterFailureCategory | None,
) -> OutboundFailureCategory | None:
    """Translate the adapter's enum into the persistence enum.

    Both enums share the same closed string values; the conversion
    is a value-based lookup so the adapter does not need to import
    the SQLAlchemy model layer.
    """
    if value is None:
        return None
    return OutboundFailureCategory(str(value.value))

_DURABLE_STATE_BY_OUTCOME: dict[OutboundDispatchOutcome, str] = {
    OutboundDispatchOutcome.SENT: "accepted",
    OutboundDispatchOutcome.RETRY_SCHEDULED: "retryable",
    OutboundDispatchOutcome.FAILED_TERMINAL: "failed_terminal",
    OutboundDispatchOutcome.NO_DUE_ROW: "no_due_row",
}

_ATTEMPT_OUTCOME_BY_DISPATCH_OUTCOME: dict[
    OutboundDispatchOutcome, OutboundAttemptOutcome
] = {
    OutboundDispatchOutcome.SENT: OutboundAttemptOutcome.SENT,
    OutboundDispatchOutcome.RETRY_SCHEDULED: (
        OutboundAttemptOutcome.RETRY_SCHEDULED
    ),
    OutboundDispatchOutcome.FAILED_TERMINAL: (
        OutboundAttemptOutcome.FAILED_TERMINAL
    ),
    OutboundDispatchOutcome.NO_DUE_ROW: OutboundAttemptOutcome.NO_DUE_ROW,
}

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], SqlSession]
OutboxRepoFactory = Callable[[SqlSession], MensajeProveedorSalienteRepository]


@dataclass(frozen=True)
class OutboundDispatchConfig:
    """Configuration snapshot consumed by the dispatcher.

    The fields are pinned at ``Settings.load()`` time so the
    dispatcher reads a single immutable snapshot. Changing any
    retry bound requires restarting the dispatcher.
    """

    sender_e164: str
    status_callback_url: str
    lease_seconds: int
    initial_backoff_seconds: int
    max_backoff_seconds: int
    max_attempts: int


class OutboundMessageDispatcher:
    """Single-owner Phase-5.6 dispatcher."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        messages_client: TwilioMessagesClient | None = None,
        config: OutboundDispatchConfig | None = None,
        outbox_repo_factory: OutboxRepoFactory | None = None,
        settings: Settings | None = None,
        now: datetime | None = None,
    ) -> None:
        if session_factory is None:
            raise ValueError(
                "OutboundMessageDispatcher requires a session_factory"
            )
        self._session_factory = session_factory
        self._settings = settings or load_settings()
        self._config = config or _config_from_settings(self._settings)
        self._messages = messages_client
        self._outbox_repo_factory = (
            outbox_repo_factory or MensajeProveedorSalienteRepository
        )
        self._now = now

    def _now_or(self) -> datetime:
        if self._now is not None:
            return self._now
        return datetime.now(tz=_utc())

    def _open_session(self) -> SqlSession:
        return self._session_factory()

    def _claim(self, now: datetime) -> MensajeProveedorSaliente | None:
        """Claim a single due row inside a narrow transaction.

        The session is committed before the function returns so the
        lease is durable; the session is always closed, including on
        the technical-failure path. The dispatcher never leaves an
        uncommitted lease behind.
        """
        session = self._open_session()
        try:
            repo = self._outbox_repo_factory(session)
            claimed = repo.claim_due(
                now=now, lease_seconds=self._config.lease_seconds
            )
            session.commit()
            return claimed
        except SQLAlchemyError as exc:
            emit_event(
                event=EVENT_DATABASE_TECHNICAL_FAILURE,
                component=COMPONENT_DATABASE,
                failure_category=categorize_sqlalchemy_error(exc),
                exception_type=type(exc).__name__,
            )
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _finalize(
        self,
        *,
        claimed: MensajeProveedorSaliente,
        send_result: TwilioSendResult,
        now: datetime,
    ) -> OutboundDispatchResult:
        """Apply the network outcome inside a narrow transaction.

        The function selects the matching finalization branch on
        ``send_result.status``, asks the repository to apply the
        conditional update with the lease token, and commits the row
        state. Technical failures inside the narrow transaction
        roll the row back and propagate so the dispatcher never
        leaves a fictitiously persisted lease.
        """
        session = self._open_session()
        try:
            repo = self._outbox_repo_factory(session)
            outcome = self._apply_finalization(
                repo=repo,
                claimed=claimed,
                send_result=send_result,
                now=now,
            )
            session.commit()
            return outcome
        except SQLAlchemyError as exc:
            emit_event(
                event=EVENT_DATABASE_TECHNICAL_FAILURE,
                component=COMPONENT_DATABASE,
                failure_category=categorize_sqlalchemy_error(exc),
                exception_type=type(exc).__name__,
            )
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _apply_finalization(
        self,
        *,
        repo: MensajeProveedorSalienteRepository,
        claimed: MensajeProveedorSaliente,
        send_result: TwilioSendResult,
        now: datetime,
    ) -> OutboundDispatchResult:
        if send_result.status is TwilioSendStatus.SENT:
            applied = repo.finalize_accepted(
                mensaje_id=int(claimed.id),
                lease_token=str(claimed.token_lease or ""),
                identificador_proveedor=str(
                    send_result.message_sid or ""
                ),
            )
            if not applied:
                logger.info(
                    "twilio_outbound_dispatch_late_acceptance",
                    extra={"outbox_id": int(claimed.id)},
                )
                return _late_acceptance(int(claimed.id))
            return _sent(
                int(claimed.id), str(send_result.message_sid or "")
            )

        if send_result.status is TwilioSendStatus.RETRYABLE:
            attempts = int(claimed.intentos)
            if attempts >= self._config.max_attempts:
                applied = repo.finalize_terminal(
                    mensaje_id=int(claimed.id),
                    lease_token=str(claimed.token_lease or ""),
                    categoria=OutboundFailureCategory.BUDGET_EXHAUSTED,
                    codigo=str(send_result.codigo or ""),
                )
                if not applied:
                    return _late_acceptance(int(claimed.id))
                return _terminal(
                    int(claimed.id),
                    attempts=attempts,
                    categoria=OutboundFailureCategory.BUDGET_EXHAUSTED,
                    codigo=str(send_result.codigo or ""),
                    http_status=(
                        int(send_result.http_status)
                        if send_result.http_status is not None
                        else None
                    ),
                )
            next_at = _compute_next_attempt_at(
                now=now,
                attempts=attempts,
                initial_seconds=self._config.initial_backoff_seconds,
                max_seconds=self._config.max_backoff_seconds,
            )
            adapter_categoria = (
                send_result.categoria
                or AdapterFailureCategory.RETRYABLE_TIMEOUT
            )
            applied = repo.finalize_retryable(
                mensaje_id=int(claimed.id),
                lease_token=str(claimed.token_lease or ""),
                categoria=_to_model_category(adapter_categoria)
                or OutboundFailureCategory.RETRYABLE_TIMEOUT,
                codigo=str(send_result.codigo or ""),
                proximo_intento_en=next_at,
            )
            if not applied:
                return _late_acceptance(int(claimed.id))
            return _retry(
                int(claimed.id),
                attempts=attempts,
                categoria=_to_model_category(adapter_categoria),
                codigo=str(send_result.codigo or ""),
                http_status=(
                    int(send_result.http_status)
                    if send_result.http_status is not None
                    else None
                ),
            )

        adapter_categoria = (
            send_result.categoria
            or AdapterFailureCategory.TERMINAL_4XX
        )
        applied = repo.finalize_terminal(
            mensaje_id=int(claimed.id),
            lease_token=str(claimed.token_lease or ""),
            categoria=_to_model_category(adapter_categoria)
            or OutboundFailureCategory.TERMINAL_4XX,
            codigo=str(send_result.codigo or ""),
        )
        if not applied:
            return _late_acceptance(int(claimed.id))
        return _terminal(
            int(claimed.id),
            attempts=int(claimed.intentos),
            categoria=_to_model_category(adapter_categoria)
            or OutboundFailureCategory.TERMINAL_4XX,
            codigo=str(send_result.codigo or ""),
            http_status=(
                int(send_result.http_status)
                if send_result.http_status is not None
                else None
            ),
        )

    def dispatch(self) -> OutboundDispatchResult:
        """Claim and dispatch exactly one due row.

        The dispatcher runs three distinct phases:

        1. claim in a narrow transaction (committed, session closed);
        2. Twilio network call OUTSIDE any database session;
        3. finalize in a separate narrow transaction.

        Returns ``no_due_row`` when no due row exists. The dispatcher
        never raises a business signal: the caller branches on
        ``outcome.outcome`` after a single ``dispatch`` call.
        Technical failures inside any narrow transaction roll back
        that transaction and propagate so the caller learns about
        them without the dispatcher swallowing them.

        The dispatcher emits one safe ``provider_outbound_attempt``
        log record per ``dispatch`` call. Typed outcomes carry
        ``outcome``, ``outbox_id``, ``attempt_count``,
        ``durable_state``, ``failure_category``, ``provider_code``
        and ``http_status`` (when known). Technical failures carry
        ``outcome=technical_failure`` and ``exception_type`` only;
        raw exception text, addresses, signatures, payloads and
        tracebacks are never logged.
        """
        now = self._now_or()
        claimed: MensajeProveedorSaliente | None = None
        send_result: TwilioSendResult | None = None
        try:
            claimed = self._claim(now)
            if claimed is None:
                result = _no_due_row()
                _emit_attempt_event(
                    event=_build_attempt_event(
                        result=result, send_result=None
                    ),
                    logger_=logger,
                )
                return result

            if self._messages is None:
                raise RuntimeError(
                    "OutboundMessageDispatcher.dispatch requires a "
                    "messages_client seam"
                )

            request = build_send_request(
                OutboundDispatchPayload(
                    destinatario_e164=str(claimed.destinatario_e164),
                    cuerpo=str(claimed.cuerpo),
                    idempotency_key=f"outbox-{int(claimed.id)}",
                ),
                sender_e164=self._config.sender_e164,
                status_callback_url=self._config.status_callback_url,
            )
            send_result = twilio_send(self._messages, request)
            result = self._finalize(
                claimed=claimed, send_result=send_result, now=now
            )
            _emit_attempt_event(
                event=_build_attempt_event(
                    result=result, send_result=send_result
                ),
                logger_=logger,
            )
            return result
        except Exception as exc:
            claimed_outbox_id = (
                int(claimed.id) if claimed is not None else None
            )
            _emit_attempt_event(
                event=_build_technical_event(
                    exc=exc, outbox_id=claimed_outbox_id
                ),
                logger_=logger,
            )
            raise

    def run_retry_pass(
        self, *, max_attempts_per_pass: int = 16
    ) -> SequenceABC[OutboundDispatchResult]:
        """Drive the dispatcher until no due row is left or the
        per-pass budget is exhausted.

        The pass is intentionally bounded so the operator entry
        point never starves. Each iteration is independent and
        re-reads ``now`` from the supplied clock so a long-running
        pass cannot lock in stale timestamps.

        Technical failures inside ``dispatch`` propagate
        unchanged; use :meth:`run_pass_with_evidence` when the
        caller needs the technical exception captured for
        per-cycle aggregates.
        """
        results: list[OutboundDispatchResult] = []
        for _ in range(int(max_attempts_per_pass)):
            outcome = self.dispatch()
            results.append(outcome)
            if outcome.outcome is OutboundDispatchOutcome.NO_DUE_ROW:
                break
        return tuple(results)

    def run_pass_with_evidence(
        self, *, max_attempts_per_pass: int = 16
    ) -> OutboundPassEvidence:
        """Drive the dispatcher and capture both typed results and
        technical exceptions.

        The pass is bounded by ``max_attempts_per_pass`` and stops
        on the first technical exception so the dispatcher never
        leaves an unrecovered lease behind. The exception is
        captured so the CLI / worker can surface the per-cycle
        technical-failure count without re-running the
        dispatcher. ``run_retry_pass`` is preserved for callers
        that need the legacy exception-propagating contract.
        """
        results: list[OutboundDispatchResult] = []
        technical_exceptions: list[BaseException] = []
        for _ in range(int(max_attempts_per_pass)):
            try:
                outcome = self.dispatch()
            except Exception as exc:  # noqa: BLE001 - dispatcher-owned technical failures must be captured for per-cycle aggregates
                technical_exceptions.append(exc)
                break
            results.append(outcome)
            if outcome.outcome is OutboundDispatchOutcome.NO_DUE_ROW:
                break
        return OutboundPassEvidence(
            results=tuple(results),
            technical_exceptions=tuple(technical_exceptions),
        )


def _emit_outbound_event(result: OutboundDispatchResult) -> None:
    """Emit a single ``outbound_attempt_outcome`` event for the result.

    The mapping is intentionally narrow:
    * SENT → outcome=accepted, durable_state=accepted;
    * RETRY_SCHEDULED → outcome=retryable, provider_code=send.codigo;
    * FAILED_TERMINAL → outcome=terminal, provider_code=send.codigo;
    * NO_DUE_ROW with detalle=late_acceptance → outcome=late_acceptance;
    * NO_DUE_ROW otherwise → outcome=no_due_row.

    The event never carries the outbound body, the destination
    E.164, the provider SID, the auth token or the raw exception
    text. Repository-side SQLAlchemy errors are emitted separately
    from ``_claim`` / ``_finalize`` so the dispatcher never
    duplicates signals.
    """
    durable_state_map = {
        OutboundDispatchOutcome.SENT: "accepted",
        OutboundDispatchOutcome.RETRY_SCHEDULED: "retryable",
        OutboundDispatchOutcome.FAILED_TERMINAL: "failed_terminal",
    }
    if result.outcome is OutboundDispatchOutcome.NO_DUE_ROW:
        outcome = (
            "late_acceptance"
            if result.detalle == "late_acceptance"
            else "no_due_row"
        )
    else:
        outcome = {
            OutboundDispatchOutcome.SENT: "accepted",
            OutboundDispatchOutcome.RETRY_SCHEDULED: "retryable",
            OutboundDispatchOutcome.FAILED_TERMINAL: "terminal",
        }[result.outcome]

    emit_event(
        event=EVENT_OUTBOUND_OUTCOME,
        component=COMPONENT_OUTBOUND,
        outcome=outcome,
        outbox_id=int(result.mensaje_id) if result.mensaje_id is not None else None,
        attempt=int(result.intentos) if result.intentos is not None else None,
        durable_state=durable_state_map.get(result.outcome),
        provider_code=str(result.codigo) if result.codigo else None,
    )


def _compute_next_attempt_at(
    *,
    now: datetime,
    attempts: int,
    initial_seconds: int,
    max_seconds: int,
) -> datetime:
    """Compute the deterministic bounded next-attempt timestamp.

    The backoff is fixed and bounded; jitter is deliberately
    excluded so focused tests can predict the next-attempt
    timestamp without relying on randomness.
    """
    safe_initial = max(1, int(initial_seconds))
    safe_max = max(safe_initial, int(max_seconds))
    delay = safe_initial * max(1, int(attempts))
    delay = min(delay, safe_max)
    return now + timedelta(seconds=int(delay))


def _config_from_settings(settings: Settings) -> OutboundDispatchConfig:
    sender = settings.twilio_outbound_sender_e164
    callback = settings.twilio_callback_status_url
    if (
        not isinstance(sender, str)
        or not sender.strip()
    ):
        raise RuntimeError(
            "TWILIO_OUTBOUND_SENDER_E164 is required by the dispatcher"
        )
    if (
        not isinstance(callback, str)
        or not callback.strip()
    ):
        raise RuntimeError(
            "TWILIO_CALLBACK_STATUS_URL is required by the dispatcher"
        )
    return OutboundDispatchConfig(
        sender_e164=sender.strip(),
        status_callback_url=callback.strip(),
        lease_seconds=int(settings.twilio_outbound_lease_seconds),
        initial_backoff_seconds=int(
            settings.twilio_outbound_initial_backoff_seconds
        ),
        max_backoff_seconds=int(settings.twilio_outbound_max_backoff_seconds),
        max_attempts=int(settings.twilio_outbound_max_attempts),
    )


def _utc():
    from datetime import timezone

    return timezone.utc


def _build_attempt_event(
    *,
    result: OutboundDispatchResult,
    send_result: TwilioSendResult | None,
) -> OutboundAttemptEvent:
    """Translate one ``OutboundDispatchResult`` into a safe event.

    Only the allowlisted safe fields are populated. The Twilio HTTP
    status is propagated from the adapter result when known;
    exception text, addresses, signatures, payloads and tracebacks
    are never included.
    """
    outcome = _ATTEMPT_OUTCOME_BY_DISPATCH_OUTCOME[result.outcome]
    outbox_id = (
        int(result.mensaje_id)
        if result.mensaje_id is not None
        else None
    )
    attempt_count = (
        int(result.intentos)
        if result.intentos is not None
        else None
    )
    durable_state: str | None = (
        str(result.durable_state)
        if result.durable_state
        else None
    )
    if durable_state is None and outbox_id is not None:
        durable_state = _DURABLE_STATE_BY_OUTCOME[result.outcome]
    failure_category: str | None = None
    provider_code: str | None = None
    http_status: int | None = (
        int(result.http_status)
        if result.http_status is not None
        else None
    )
    if result.outcome in (
        OutboundDispatchOutcome.RETRY_SCHEDULED,
        OutboundDispatchOutcome.FAILED_TERMINAL,
    ):
        if result.categoria is not None:
            failure_category = str(result.categoria.value)
        if result.codigo:
            provider_code = str(result.codigo)
        if http_status is None and send_result is not None:
            http_status = (
                int(send_result.http_status)
                if send_result.http_status is not None
                else None
            )
    return OutboundAttemptEvent(
        outcome=outcome,
        outbox_id=outbox_id,
        attempt_count=attempt_count,
        durable_state=durable_state,
        failure_category=failure_category,
        provider_code=provider_code,
        http_status=http_status,
        exception_type=None,
    )


def _build_technical_event(
    *, exc: BaseException, outbox_id: int | None
) -> OutboundAttemptEvent:
    """Translate an unexpected exception into a safe technical event.

    Only the exception class is exposed. Raw exception text, body
    bytes, addresses, signatures, payloads and tracebacks are
    forbidden. ``outbox_id`` is populated only when the dispatcher
    had already claimed a row before the exception; it remains
    ``None`` when the failure happened before any claim so the
    record never fabricates a durable context.
    """
    safe_outbox_id = int(outbox_id) if outbox_id is not None else None
    return OutboundAttemptEvent(
        outcome=OutboundAttemptOutcome.TECHNICAL_FAILURE,
        outbox_id=safe_outbox_id,
        attempt_count=None,
        durable_state=None,
        failure_category=None,
        provider_code=None,
        http_status=None,
        exception_type=type(exc).__name__,
    )


def _attempt_event_extra(event: OutboundAttemptEvent) -> dict[str, Any]:
    """Render an ``OutboundAttemptEvent`` as a logging ``extra`` payload.

    The payload contains only the allowlisted safe fields; every
    value is explicitly typed so the operator logging surface is
    uniform regardless of the outcome. ``None`` values are dropped
    so the log record never advertises an empty field.
    """
    payload: dict[str, Any] = {
        "outcome": str(event.outcome.value),
    }
    if event.outbox_id is not None:
        payload["outbox_id"] = int(event.outbox_id)
    if event.attempt_count is not None:
        payload["attempt_count"] = int(event.attempt_count)
    if event.durable_state is not None:
        payload["durable_state"] = str(event.durable_state)
    if event.failure_category is not None:
        payload["failure_category"] = str(event.failure_category)
    if event.provider_code is not None:
        payload["provider_code"] = str(event.provider_code)
    if event.http_status is not None:
        payload["http_status"] = int(event.http_status)
    if event.exception_type is not None:
        payload["exception_type"] = str(event.exception_type)
    return payload


def _emit_attempt_event(
    *, event: OutboundAttemptEvent, logger_: logging.Logger
) -> None:
    """Emit one safe ``provider_outbound_attempt`` log record.

    The event name is fixed and the payload is restricted to the
    allowlisted fields via :func:`_attempt_event_extra`. The
    function never attaches exception info, addresses, signatures,
    payloads, bodies or tracebacks.
    """
    logger_.info(
        "provider_outbound_attempt",
        extra=_attempt_event_extra(event),
    )


def _no_due_row() -> OutboundDispatchResult:
    return OutboundDispatchResult(
        outcome=OutboundDispatchOutcome.NO_DUE_ROW,
        mensaje_id=None,
        identificador_proveedor=None,
        intentos=None,
        categoria=None,
        codigo=None,
        detalle="no_due_row",
    )


def _late_acceptance(outbox_id: int) -> OutboundDispatchResult:
    return OutboundDispatchResult(
        outcome=OutboundDispatchOutcome.NO_DUE_ROW,
        mensaje_id=outbox_id,
        identificador_proveedor=None,
        intentos=None,
        categoria=None,
        codigo=None,
        detalle="late_acceptance",
    )


def _sent(outbox_id: int, message_sid: str) -> OutboundDispatchResult:
    return OutboundDispatchResult(
        outcome=OutboundDispatchOutcome.SENT,
        mensaje_id=outbox_id,
        identificador_proveedor=message_sid,
        intentos=None,
        categoria=None,
        codigo=None,
        durable_state="accepted",
        detalle=None,
    )


def _retry(
    outbox_id: int,
    *,
    attempts: int,
    categoria: OutboundFailureCategory | None,
    codigo: str,
    http_status: int | None = None,
) -> OutboundDispatchResult:
    return OutboundDispatchResult(
        outcome=OutboundDispatchOutcome.RETRY_SCHEDULED,
        mensaje_id=outbox_id,
        identificador_proveedor=None,
        intentos=attempts,
        categoria=categoria,
        codigo=codigo,
        durable_state="retryable",
        http_status=http_status,
        detalle=None,
    )


def _terminal(
    outbox_id: int,
    *,
    attempts: int,
    categoria: OutboundFailureCategory,
    codigo: str,
    http_status: int | None = None,
) -> OutboundDispatchResult:
    return OutboundDispatchResult(
        outcome=OutboundDispatchOutcome.FAILED_TERMINAL,
        mensaje_id=outbox_id,
        identificador_proveedor=None,
        intentos=attempts,
        categoria=categoria,
        codigo=codigo,
        durable_state="failed_terminal",
        http_status=http_status,
        detalle=None,
    )


__all__ = [
    "OutboundDispatchConfig",
    "OutboundMessageDispatcher",
    "OutboxRepoFactory",
    "SessionFactory",
]
