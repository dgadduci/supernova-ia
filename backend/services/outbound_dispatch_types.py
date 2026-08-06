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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class OutboundDispatchResult:
    """Immutable Phase-5.6 dispatcher outcome.

    ``outcome`` is the single source of truth for branching. Every
    other field is only meaningful for the matching non-empty outcome;
    non-applicable fields are ``None``. Raw outbound body bytes never
    reach the result so observability surfaces cannot leak provider
    payload data.
    """

    outcome: OutboundDispatchOutcome
    mensaje_id: int | None
    identificador_proveedor: str | None
    intentos: int | None
    categoria: OutboundFailureCategory | None
    codigo: str | None
    detalle: str | None


__all__ = [
    "OutboundDispatchOutcome",
    "OutboundDispatchResult",
]