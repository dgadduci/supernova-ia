from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def process_incoming_message_transactional(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> list[ProcessedIntent]:
    try:
        if sink is None:
            result = process_incoming_message(db, session, message)
        else:
            result = process_incoming_message(db, session, message, sink=sink)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return result


__all__ = ["process_incoming_message_transactional"]