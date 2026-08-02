from typing import TYPE_CHECKING

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.schemas.pending_intents import PendingIntents
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import clear, set_active

if TYPE_CHECKING:
    from backend.models.session import Session as SessionModel


def set_pending_intent(session: "SessionModel", intent: ProcessedIntent) -> PendingIntents:
    if intent.status != "pending_resolution":
        raise ValueError(
            f"intent.status must be 'pending_resolution' (got '{intent.status}')"
        )
    context_type = resolve_context_type(intent)
    if context_type is None:
        raise ValueError("no ContextType can be resolved for the given intent")
    state = set_active(session, intent)
    session.context_type = context_type.value
    return state


def clear_pending_context(session: "SessionModel") -> None:
    clear(session)
    session.context_type = None


__all__ = ["set_pending_intent", "clear_pending_context"]