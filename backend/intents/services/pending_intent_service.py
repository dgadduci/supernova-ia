from typing import TYPE_CHECKING

from backend.intents.schemas.pending_intents import PendingIntents
from backend.intents.schemas.processed_intent import ProcessedIntent

if TYPE_CHECKING:
    from backend.models.session import Session as SessionModel


def _save(session: "SessionModel", state: PendingIntents) -> None:
    session.pending_intents = state.model_dump(mode="json")


def load(session: "SessionModel") -> PendingIntents:
    return PendingIntents.model_validate(session.pending_intents or {})


def set_active(session: "SessionModel", intent: ProcessedIntent) -> PendingIntents:
    current = load(session)
    new_state = current.model_copy(update={"active": intent})
    _save(session, new_state)
    return new_state


def enqueue(session: "SessionModel", intent: ProcessedIntent) -> PendingIntents:
    current = load(session)
    new_queue = [*current.queue, intent]
    new_state = current.model_copy(update={"queue": new_queue})
    _save(session, new_state)
    return new_state


def remove_active(session: "SessionModel") -> PendingIntents:
    current = load(session)
    if current.queue:
        new_active = current.queue[0]
        new_queue = current.queue[1:]
    else:
        new_active = None
        new_queue = []
    new_state = current.model_copy(update={"active": new_active, "queue": new_queue})
    _save(session, new_state)
    return new_state


def clear(session: "SessionModel") -> None:
    _save(session, PendingIntents())


__all__ = ["load", "set_active", "enqueue", "remove_active", "clear"]