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
from backend.intents.orchestration.order_status_query import (
    is_explicit_order_status_query,
    process_initial_order_status_query,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import clear as clear_pending_state
from backend.intents.services.pending_intent_service import load as load_pending_state
from backend.intents.services.pending_intent_service import set_active
from backend.models.session import Session as ConversationSession
from backend.observability.events import (
    COMPONENT_PENDING_CONTEXT,
    EVENT_PENDING_CONTEXT_TRANSITION,
    emit_event,
)
from backend.sessions.enums.context_type import ContextType

_SUPPORTED_CONTEXT_KINDS: frozenset[str] = frozenset(
    {
        ContextType.PRODUCT_SELECTION.value,
        ContextType.ORDER_LINE_SELECTION.value,
        ContextType.PRODUCT_MODIFICATION.value,
        ContextType.ORDER_CLEAR_CONFIRMATION.value,
    }
)


def _rejected_copy(active: ProcessedIntent) -> ProcessedIntent:
    return active.model_copy(update={"status": "rejected"})


def _candidate_count(active: ProcessedIntent | None) -> int:
    if active is None:
        return 0
    return len(active.candidate_ids or [])


def _emit_pending_transition(
    *,
    outcome: str,
    context_kind: str,
    status_before: str,
    status_after: str,
    candidate_count_before: int,
    candidate_count_after: int,
    context_cleared: bool,
) -> None:
    candidate_count_before = max(candidate_count_before, 0)
    candidate_count_after = max(candidate_count_after, 0)
    try:
        emit_event(
            event=EVENT_PENDING_CONTEXT_TRANSITION,
            component=COMPONENT_PENDING_CONTEXT,
            outcome=outcome,
            context_kind=context_kind,
            status_before=status_before,
            status_after=status_after,
            candidate_count_before=candidate_count_before,
            candidate_count_after=candidate_count_after,
            context_cleared=context_cleared,
        )
    except Exception:  # noqa: BLE001 - emission is best effort, never raises
        return


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


def _supported_context_kind(context_type: str | None) -> str | None:
    if context_type is None:
        return None
    if context_type in _SUPPORTED_CONTEXT_KINDS:
        return context_type
    return None


def _run_supported_resolver(
    *,
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active: ProcessedIntent,
    diagnostic_sink: DiagnosticSink,
) -> ProcessedIntent:
    context_kind = session.context_type
    if context_kind == ContextType.PRODUCT_SELECTION.value:
        return ProductSelectionContextService(
            db, sink=diagnostic_sink
        ).resolve(message, active, commerce_id=session.id_comercio)
    if context_kind == ContextType.ORDER_LINE_SELECTION.value:
        return resolve_order_line_selection(
            db, session, message, active, sink=diagnostic_sink
        )
    if context_kind == ContextType.PRODUCT_MODIFICATION.value:
        return resolve_product_modification(
            db, session, message, active, sink=diagnostic_sink
        )
    if context_kind == ContextType.ORDER_CLEAR_CONFIRMATION.value:
        return resolve_order_clear_confirmation(
            db, session, message, active, sink=diagnostic_sink
        )
    return _rejected_copy(active)


def _derive_post_execution_trace(
    *,
    executed: list[ProcessedIntent],
    post_state,
    session: ConversationSession,
) -> tuple[str, str, int, bool]:
    """Determine the trace outcome, status_after, candidate_count_after
    and context_cleared from the actual ready-execution results and
    the effective persisted session/pending state.

    The trace must reflect what actually happened: an ``executed``
    result that cleared the context surfaces as
    ``ready_executed`` / ``status_after=executed`` /
    ``context_cleared=True``; a promoted pending surfaces as
    ``pending_preserved`` / ``status_after=pending_resolution`` /
    ``context_cleared=False``; a ``rejected`` result that cleared
    the context surfaces as ``rejected_cleared``; a ``failed``
    result keeps the pending state and surfaces as
    ``pending_preserved`` / ``status_after=failed`` /
    ``context_cleared=False``. No closed outcome is invented for a
    fake ``status_after=ready`` / ``context_cleared=False`` case.
    """
    context_cleared = session.context_type is None
    new_active = post_state.active
    first = executed[0] if executed else None

    if first is not None and first.status == "executed" and context_cleared:
        return (
            "ready_executed",
            "executed",
            _candidate_count(first),
            True,
        )

    if first is not None and first.status == "rejected" and context_cleared:
        return (
            "rejected_cleared",
            "rejected",
            _candidate_count(first),
            True,
        )

    if (
        not context_cleared
        and new_active is not None
        and new_active.status == "pending_resolution"
    ):
        return (
            "pending_preserved",
            new_active.status,
            _candidate_count(new_active),
            False,
        )

    if first is not None and first.status == "failed" and not context_cleared:
        return (
            "pending_preserved",
            "failed",
            _candidate_count(first),
            False,
        )

    if new_active is not None:
        return (
            "pending_preserved",
            new_active.status,
            _candidate_count(new_active),
            context_cleared,
        )

    if first is not None:
        return (
            "pending_preserved",
            first.status,
            _candidate_count(first),
            context_cleared,
        )

    return ("pending_preserved", "ready", 0, context_cleared)


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
    context_kind = _supported_context_kind(session.context_type)
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

    if (
        context_kind is not None
        and is_explicit_order_status_query(message)
    ):
        status_intent = process_initial_order_status_query(db, session, message)
        pre_candidate_count = _candidate_count(active)
        _emit_pending_transition(
            outcome="status_interrupted",
            context_kind=context_kind,
            status_before=active.status,
            status_after=status_intent.status,
            candidate_count_before=pre_candidate_count,
            candidate_count_after=pre_candidate_count,
            context_cleared=False,
        )
        return [status_intent]

    if session.context_type is None:
        return [_rejected_copy(active)]

    if context_kind is None:
        return [_rejected_copy(active)]

    result = _run_supported_resolver(
        db=db,
        session=session,
        message=message,
        active=active,
        diagnostic_sink=diagnostic_sink,
    )
    pre_candidate_count = _candidate_count(active)

    if result.status == "rejected":
        clear_pending_state(session)
        session.context_type = None
        post_state = load_pending_state(session)
        _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")
        _emit_pending_transition(
            outcome="rejected_cleared",
            context_kind=context_kind,
            status_before=active.status,
            status_after="rejected",
            candidate_count_before=pre_candidate_count,
            candidate_count_after=_candidate_count(result),
            context_cleared=True,
        )
        return [result]

    set_active(session, result)
    post_state = load_pending_state(session)
    _emit_pending_snapshot(diagnostic_sink, session, post_state, "after_resolver")

    if result.status == "ready":
        executed = execute_ready_pending_context(db, session)
        post_exec_state = load_pending_state(session)
        outcome, status_after, candidate_count_after, context_cleared = (
            _derive_post_execution_trace(
                executed=executed,
                post_state=post_exec_state,
                session=session,
            )
        )
        _emit_pending_transition(
            outcome=outcome,
            context_kind=context_kind,
            status_before=active.status,
            status_after=status_after,
            candidate_count_before=pre_candidate_count,
            candidate_count_after=candidate_count_after,
            context_cleared=context_cleared,
        )
        return executed

    _emit_pending_transition(
        outcome="pending_preserved",
        context_kind=context_kind,
        status_before=active.status,
        status_after=result.status,
        candidate_count_before=pre_candidate_count,
        candidate_count_after=_candidate_count(result),
        context_cleared=False,
    )
    return [result]


__all__ = ["dispatch_pending_context"]
