from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.transactional_message_processor import (
    process_incoming_message_transactional,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.models.session import Session as ConversationSession
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,  # noqa: F401  -- re-exported for legacy imports
    build_customer_responses,
)

__all__ = ["process_incoming_message_with_responses"]


def process_incoming_message_with_responses(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> list[CustomerResponse]:
    if sink is None:
        processed = process_incoming_message_transactional(db, session, message)
    else:
        processed = process_incoming_message_transactional(
            db, session, message, sink=sink
        )

    return build_customer_responses(db, session, processed, sink=sink)
