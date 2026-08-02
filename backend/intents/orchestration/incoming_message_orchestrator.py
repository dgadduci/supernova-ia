from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import NoopDiagnosticSink
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def process_incoming_message(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> list[ProcessedIntent]:
    if not isinstance(message, str):
        raise TypeError("message must be a str")
    if not message.strip():
        raise ValueError("message must be a non-empty, non-whitespace string")

    if sink is None:
        if session.context_type is not None:
            return dispatch_pending_context(db, session, message)
        return dispatch_initial_message(db, session, message)
    if session.context_type is not None:
        return dispatch_pending_context(db, session, message, sink=sink)
    return dispatch_initial_message(db, session, message, sink=sink)


__all__ = ["process_incoming_message"]
