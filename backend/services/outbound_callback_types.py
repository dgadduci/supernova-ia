"""Phase-5.6 Twilio delivery callback typed contracts.

The callback service is the only component in Phase 5.6 that maps a
signed Twilio status callback onto a monotonic outbox-row transition.
It returns a small set of typed outcomes so the router can observe
each callback and so focused tests can branch on a single attribute.

The service never imports HTTP, FastAPI, the Twilio SDK, the
coordinator, the resolver, the dispatcher or the response
orchestrator; it talks only to the repository.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class OutboundCallbackOutcome(str, enum.Enum):
    """Typed outcomes returned by
    ``TwilioDeliveryCallbackService.apply_callback``.

    Every value maps to a single non-resolved or resolved state. The
    service never raises a business-outcome signal; callers branch on
    ``outcome.outcome`` after a single ``apply_callback`` call.
    """

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"
    REGRESSION = "regression"


@dataclass(frozen=True)
class OutboundCallbackResult:
    """Immutable Phase-5.6 callback outcome.

    ``outcome`` is the single source of truth for branching. The other
    fields are only meaningful for the matching ``applied`` outcome;
    non-applicable fields are ``None``. Raw callback payload bytes
    never reach the result so observability surfaces cannot leak
    provider payload data.
    """

    outcome: OutboundCallbackOutcome
    mensaje_id: int | None
    estado_anterior: str | None
    estado_nuevo: str | None


__all__ = [
    "OutboundCallbackOutcome",
    "OutboundCallbackResult",
]