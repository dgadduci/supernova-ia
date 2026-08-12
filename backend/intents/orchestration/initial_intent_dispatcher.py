from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import NoopDiagnosticSink, PendingStateSnapshot
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.agregar_producto_orchestrator import (
    process_initial_agregar_producto,
)
from backend.intents.orchestration.draft_order_closure import (
    process_initial_confirmar_pedido,
    process_initial_consultar_resumen_pedido,
    process_initial_set_metodo_de_entrega,
    process_initial_set_metodo_de_pago,
    process_initial_set_observacion_pedido,
)
from backend.intents.orchestration.informational_commerce_queries import (
    is_informational_commerce_intent,
    process_initial_informational_commerce_query,
)
from backend.intents.orchestration.modificar_producto_initial import (
    process_initial_modificar_producto,
)
from backend.intents.orchestration.new_order_after_confirmation import (
    process_initial_iniciar_pedido,
)
from backend.intents.orchestration.order_status_query import (
    process_initial_order_status_query,
)
from backend.intents.orchestration.quitar_producto_initial import (
    process_initial_quitar_producto,
)
from backend.intents.orchestration.vaciar_pedido_initial import (
    process_initial_vaciar_pedido,
)
from backend.intents.responses.social_conversation_response import (
    SOCIAL_CONVERSATION_HANDLER,
    is_social_conversation_intent,
)
from backend.intents.schemas.intent_classification import IntentName
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import load as load_pending_state
from backend.llm.intent_classifier import IntentClassifier
from backend.models.session import Session as ConversationSession


def dispatch_initial_message(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> list[ProcessedIntent]:
    if session.context_type is not None:
        return []

    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    try:
        state = load_pending_state(session)
        active_intent = state.active
        queued_count = len(state.queue)
    except Exception:
        state = None
        active_intent = None
        queued_count = 0
    if state is not None:
        diagnostic_sink.on_pending_state_snapshot(
            PendingStateSnapshot(
                snapshot_phase="before_classifier",
                active_intent=active_intent.intent if active_intent is not None else None,
                active_status=active_intent.status if active_intent is not None else None,
                active_source_text=(
                    active_intent.source_text if active_intent is not None else None
                ),
                active_quantity=(
                    (active_intent.resolved_data or {}).get("cantidad")
                    if active_intent is not None
                    else None
                ),
                active_candidate_ids=list(active_intent.candidate_ids)
                if active_intent is not None
                else [],
                queue_length=queued_count,
                queue_intents=[item.intent for item in state.queue],
                queue_sources=[item.source_text for item in state.queue],
                context_type=session.context_type,
            )
        )

    if sink is None:
        classifier = IntentClassifier()
    else:
        classifier = IntentClassifier(sink=diagnostic_sink)
    if isinstance(diagnostic_sink, NoopDiagnosticSink):
        result = classifier.query(message)
    else:
        result = classifier.query(
            message,
            active_context_type=session.context_type,
            active_pending_intent=active_intent.intent
            if active_intent is not None
            else None,
            queued_intent_count=queued_count,
        )

    processed: list[ProcessedIntent] = []
    active_boundary_reached = False
    session_replaced = False
    for classified in result.intents:
        classified_intent = classified.intent

        if session_replaced:
            continue

        if classified_intent == IntentName.AGREGAR_PRODUCTO:
            if active_boundary_reached:
                process_initial_agregar_producto(
                    db, session, classified.mensaje
                )
                continue
            new_intent = process_initial_agregar_producto(
                db, session, classified.mensaje
            )
            processed.append(new_intent)
            if new_intent.status == "pending_resolution":
                active_boundary_reached = True
            continue

        if classified_intent == IntentName.QUITAR_PRODUCTO:
            processed.append(
                process_initial_quitar_producto(db, session, classified.mensaje)
            )
            continue

        if classified_intent == IntentName.MODIFICAR_PRODUCTO:
            processed.append(
                process_initial_modificar_producto(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.CONSULTAR_RESUMEN_PEDIDO:
            processed.append(
                process_initial_consultar_resumen_pedido(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.SET_METODO_DE_PAGO:
            processed.append(
                process_initial_set_metodo_de_pago(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.SET_METODO_DE_ENTREGA:
            processed.append(
                process_initial_set_metodo_de_entrega(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.CONFIRMAR_PEDIDO:
            processed.append(
                process_initial_confirmar_pedido(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.SET_OBSERVACION_PEDIDO:
            processed.append(
                process_initial_set_observacion_pedido(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.VACIAR_PEDIDO:
            processed.append(
                process_initial_vaciar_pedido(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.CONSULTAR_ESTADO_PEDIDO:
            processed.append(
                process_initial_order_status_query(
                    db, session, classified.mensaje
                )
            )
            continue

        if classified_intent == IntentName.INICIAR_PEDIDO:
            if active_boundary_reached:
                continue
            new_intent = process_initial_iniciar_pedido(
                db, session, classified.mensaje
            )
            processed.append(new_intent)
            if new_intent.status == "executed":
                session_replaced = True
            continue

        if is_informational_commerce_intent(classified_intent.value):
            processed.append(
                process_initial_informational_commerce_query(
                    db, session, classified
                )
            )
            continue

        if is_social_conversation_intent(classified_intent.value):
            processed.append(
                ProcessedIntent(
                    intent=classified_intent.value,
                    source_text=classified.mensaje,
                    status="executed",
                    recognizer="intent_classifier",
                    handler=SOCIAL_CONVERSATION_HANDLER,
                )
            )
            continue

        processed.append(
            ProcessedIntent(
                intent=classified_intent.value,
                source_text=classified.mensaje,
                status="rejected",
                recognizer="intent_classifier",
                handler=classified_intent.value,
            )
        )

    return processed


__all__ = ["dispatch_initial_message"]
