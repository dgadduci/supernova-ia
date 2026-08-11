"""Phase-5.6 outbound dispatcher typed contracts.

The dispatcher is the only component in Phase 5.6 that owns the lease
release and the conditional finalization of the outbox row. It returns
a small set of typed outcomes so the operator entry point can observe
each attempt and so focused tests can branch on a single attribute.

The dispatcher never imports HTTP, FastAPI, the Twilio SDK, the
coordinator, the resolver or the response orchestrator; it talks only
to the repository and the adapter.
"""
from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field

from backend.models.mensaje_proveedor_saliente import (
    OutboundFailureCategory,
)


class OutboundDispatchOutcome(str, enum.Enum):
    """Typed outcomes returned by ``OutboundMessageDispatcher.dispatch``.

    Every value maps to a single non-resolved or resolved state. The
    dispatcher never raises a business-outcome signal; callers branch
    on ``outcome.outcome`` after a single ``dispatch`` call.
    """

    SENT = "sent"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED_TERMINAL = "failed_terminal"
    NO_DUE_ROW = "no_due_row"


class OutboundAttemptOutcome(str, enum.Enum):
    """Typed outcomes emitted by ``provider_outbound_attempt`` events.

    The enum mirrors :class:`OutboundDispatchOutcome` for normal
    results and adds a typed ``technical_failure`` value for
    unexpected programming / configuration exceptions that escape
    the Twilio SDK seam. The ``technical_failure`` value is the
    only safe way to surface an exception class; raw exception
    text, addresses, URLs, signatures, payloads and tracebacks
    are never logged.
    """

    SENT = "sent"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED_TERMINAL = "failed_terminal"
    NO_DUE_ROW = "no_due_row"
    TECHNICAL_FAILURE = "technical_failure"


@dataclass(frozen=True)
class OutboundDispatchResult:
    """Immutable Phase-5.6 dispatcher outcome.

    ``outcome`` is the single source of truth for branching. Every
    other field is only meaningful for the matching non-empty outcome;
    non-applicable fields are ``None``. Raw outbound body bytes never
    reach the result so observability surfaces cannot leak provider
    payload data.

    The optional ``durable_state`` and ``http_status`` fields expose
    the safe post-finalization state and the Twilio HTTP status
    when known so the CLI / worker can build per-attempt evidence
    and per-cycle aggregates without leaking the underlying
    exception text.
    """

    outcome: OutboundDispatchOutcome
    mensaje_id: int | None
    identificador_proveedor: str | None
    intentos: int | None
    categoria: OutboundFailureCategory | None
    codigo: str | None
    durable_state: str | None = None
    http_status: int | None = None
    detalle: str | None = None


@dataclass(frozen=True)
class OutboundAttemptEvent:
    """Immutable sanitized outbound attempt record.

    The dispatcher emits one record per completed
    ``OutboundMessageDispatcher.dispatch`` call. The fixed event
    name is ``provider_outbound_attempt``. Only the allowlisted
    fields below are populated; raw body bytes, E.164 addresses,
    URLs, signatures, credentials, account identifiers, provider
    payloads, exception messages and tracebacks are never included
    in this record or in any log entry derived from it.

    Field usage:

    * ``outcome`` is always present.
    * ``outbox_id`` is present for claimed-row results
      (``sent``, ``retry_scheduled``, ``failed_terminal``).
    * ``attempt_count`` is present for retry / terminal results.
    * ``durable_state`` is present for accepted / retry / terminal
      results and reports the post-finalization state.
    * ``failure_category`` and ``provider_code`` are present for
      classified failures only.
    * ``http_status`` is present for classified REST failures when
      the Twilio SDK exposes the HTTP status.
    * ``exception_type`` is present for technical failures only.
    """

    outcome: OutboundAttemptOutcome
    outbox_id: int | None = None
    attempt_count: int | None = None
    durable_state: str | None = None
    failure_category: str | None = None
    provider_code: str | None = None
    http_status: int | None = None
    exception_type: str | None = None


@dataclass(frozen=True)
class OutboundCycleAggregate:
    """Per-cycle safe aggregate counts.

    The CLI and the worker build one aggregate per outbound pass.
    The aggregate exposes only counts (no bodies, no addresses, no
    exception text). The ``failure_category_counts`` mapping carries
    the per-category breakdown for retry and terminal results so
    the worker cycle summary is operationally diagnosable without
    reducing a terminal Twilio failure to a single exit code.
    """

    sent: int = 0
    retry_scheduled: int = 0
    failed_terminal: int = 0
    no_due_row: int = 0
    technical_failure: int = 0
    failure_category_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundPassEvidence:
    """Aggregate of one bounded outbound pass.

    Combines the typed per-attempt results with the technical
    exceptions that aborted the loop so the CLI / worker can
    emit per-cycle aggregates and exit codes without losing
    safe evidence about the failure. Exception instances are
    captured by class only downstream; raw text and tracebacks
    never reach the operator log.
    """

    results: tuple[OutboundDispatchResult, ...]
    technical_exceptions: tuple[BaseException, ...]


__all__ = [
    "OutboundAttemptEvent",
    "OutboundAttemptOutcome",
    "OutboundCycleAggregate",
    "OutboundDispatchOutcome",
    "OutboundDispatchResult",
    "OutboundPassEvidence",
]
