from typing import cast

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.handlers.agregar_producto_handler import execute_agregar_producto
from backend.intents.processor import process_agregar_producto
from backend.intents.resolvers.product_intent_resolver import resolve_product_intent
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import enqueue
from backend.intents.services.pending_intent_service import load as load_pending_state
from backend.models.session import Session as ConversationSession
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import ProductRecognizerProtocol
from backend.services.producto_query_service import ProductoQueryService

_product_recognizer: ProductRecognizerProtocol = FuzzyProductRecognizer()
detectar_productos = _product_recognizer.recognize


def process_initial_agregar_producto(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    catalog = ProductoQueryService(db).list_recognizer_catalog(session.id_comercio)
    recognized = detectar_productos(source_text, catalog)
    normalized = resolve_product_intent(cast(dict, recognized))
    processed_intent = process_agregar_producto(source_text, normalized)

    if processed_intent.status == "pending_resolution" and resolve_context_type(
        processed_intent
    ) is not None:
        state = load_pending_state(session)
        if state.active is None:
            set_pending_intent(session, processed_intent)
        elif (
            state.active.handler == "agregar_producto"
            and session.context_type == "product_selection"
        ):
            enqueue(session, processed_intent)
        else:
            set_pending_intent(session, processed_intent)
    elif processed_intent.status == "ready":
        state = load_pending_state(session)
        if (
            state.active is not None
            and state.active.handler == "agregar_producto"
            and session.context_type == "product_selection"
        ):
            enqueue(session, processed_intent)
        else:
            return execute_agregar_producto(db, session, processed_intent)

    return processed_intent


__all__ = ["process_initial_agregar_producto"]
