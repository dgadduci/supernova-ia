from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import NoopDiagnosticSink, PendingStateSnapshot
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.context.order_clear_confirmation_resolver import (
    resolve_order_clear_confirmation,
)
from backend.intents.context.order_line_selection_resolver import (
    resolve_order_line_selection,
)
from backend.intents.context.product_modification_resolver import (
    resolve_product_modification,
)
from backend.intents.context.product_selection_context_service import (
    ProductSelectionContextService,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import load as load_pending_state
from backend.intents.services.pending_intent_service import set_active
from backend.models.session import Session as ConversationSession
from backend.sessions.enums.context_type import ContextType


def _rejected_copy(active: ProcessedIntent) -> ProcessedIntent:
    return active.model_copy(update={"status": "rejected"})


def _emit_pending_snapshot(
    sink: DiagnosticSink,
    session: ConversationSession,
    state,
    phase: str,
) -> None:
    active = state.active
    sink.on_pending_state_snapshot(
        PendingStateSnapshot(
            snapshot_phase=phase,
            active_intent=active.intent if active is not None else None,
            active_status=active.status if active is not None else None,
            active_source_text=(
                active.source_text if active is not None else None
            ),
            active_quantity=(
                (active.resolved_data or {}).get("cantidad")
                if active is not None
                else None
            ),
            active_candidate_ids=list(active.candidate_ids)
            if active is not None
            else [],
            queue_length=len(state.queue),
            queue_intents=[item.intent for item in state.queue],
            queue_sources=[item.source_text for item in state.queue],
            context_type=session.context_type,
        )
    )


def dispatch_pending_context(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    *,
    sink: DiagnosticSink | None = None,
) -> list[ProcessedIntent]:
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    state = load_pending_state(session)
    active = state.active
    _emit_pending_snapshot(diagnostic_sink, session, state, "before_resolver")
    if active is None:
        return [ProcessedIntent(
            intent="agregar_producto",
            source_text=message,
            status="rejected",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )]
    if session.context_type is None:
        return [_rejected_copy(active)]

    if session.context_type == ContextType.PRODUCT_SELECTION.value:
        result = ProductSelectionContextService(
            db, sink=diagnostic_sink
        ).resolve(message, active)
        set_active(session, result)
        post_state = load_pending_state(session)
        _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")
        if result.status == "ready":
            return execute_ready_pending_context(db, session)
        return [result]

    if session.context_type == ContextType.ORDER_LINE_SELECTION.value:
        result = resolve_order_line_selection(
            db, session, message, active, sink=diagnostic_sink
        )
        set_active(session, result)
        post_state = load_pending_state(session)
        _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")
        if result.status == "ready":
            return execute_ready_pending_context(db, session)
        return [result]

    if session.context_type == ContextType.PRODUCT_MODIFICATION.value:
        result = resolve_product_modification(
            db, session, message, active, sink=diagnostic_sink
        )
        set_active(session, result)
        post_state = load_pending_state(session)
        _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")
        if result.status == "ready":
            return execute_ready_pending_context(db, session)
        return [result]

    if session.context_type == ContextType.ORDER_CLEAR_CONFIRMATION.value:
        result = resolve_order_clear_confirmation(
            db, session, message, active, sink=diagnostic_sink
        )
        set_active(session, result)
        post_state = load_pending_state(session)
        _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")
        if result.status == "ready":
            return execute_ready_pending_context(db, session)
        return [result]

    return [_rejected_copy(active)]


__all__ = ["dispatch_pending_context"]
