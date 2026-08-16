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
    build_customer_responses_with_diagnostic,
)
from backend.services.outbound_response_styler import StyleDiagnostic

__all__ = [
    "process_incoming_message_with_responses",
    "process_incoming_message_with_style_diagnostic",
]


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


def process_incoming_message_with_style_diagnostic(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> tuple[list[CustomerResponse], StyleDiagnostic]:
    """Opt-in companion that returns the local normal-flow
    ``CustomerResponse`` list plus the closed styling diagnostic.

    The function follows the same classification, orchestration
    and mapper path as
    :func:`process_incoming_message_with_responses`. It only
    switches the final mapper call to the opt-in companion
    :func:`backend.services.outbound_response_mapper.build_customer_responses_with_diagnostic`,
    so the response list and the diagnostic come from the same
    single styling pass. The transactional message processor
    remains the sole commit/rollback authority; the orchestrator
    does not call any transaction-control method.

    The companion is request-scoped, ephemeral, never persisted,
    never sent to the provider outbox and never used as business
    input. Any existing caller of
    :func:`process_incoming_message_with_responses` is unaffected
    by this companion.
    """
    if sink is None:
        processed = process_incoming_message_transactional(db, session, message)
    else:
        processed = process_incoming_message_transactional(
            db, session, message, sink=sink
        )

    return build_customer_responses_with_diagnostic(
        db, session, processed, sink=sink
    )
