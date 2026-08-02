from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.transactional_message_processor import (
    process_incoming_message_transactional,
)
from backend.intents.responses.agregar_producto_response import (
    build_agregar_producto_response,
)
from backend.intents.responses.modificar_producto_response import (
    build_modificar_producto_response,
)
from backend.intents.responses.quitar_producto_response import (
    build_quitar_producto_response,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

GENERIC_MESSAGE = "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?"


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

    responses: list[CustomerResponse] = []
    for intent in processed:
        if intent.intent == "agregar_producto":
            responses.append(build_agregar_producto_response(db, session, intent))
        elif intent.intent == "quitar_producto":
            responses.append(build_quitar_producto_response(db, session, intent))
        elif intent.intent == "modificar_producto":
            responses.append(build_modificar_producto_response(db, session, intent))
        else:
            responses.append(
                CustomerResponse(
                    message=GENERIC_MESSAGE,
                    intent=intent.intent,
                    status=intent.status,
                )
            )
    return responses


__all__ = ["process_incoming_message_with_responses"]
