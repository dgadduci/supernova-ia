from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.context.pending_context_service import clear_pending_context
from backend.intents.handlers.agregar_producto_handler import execute_agregar_producto
from backend.intents.handlers.modificar_producto_handler import (
    execute_modificar_producto,
)
from backend.intents.handlers.quitar_producto_handler import execute_quitar_producto
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.services.pending_intent_service import load as load_pending_state
from backend.intents.services.pending_intent_service import remove_active
from backend.models.session import Session as ConversationSession

_REJECTED_INTENT = ProcessedIntent(
    intent="agregar_producto",
    source_text="",
    status="rejected",
    recognizer="recognizer_productos",
    handler="agregar_producto",
    resolved_data={},
    requirements=[],
    candidate_ids=[],
)


def execute_ready_pending_context(
    db: DatabaseSession,
    session: ConversationSession,
) -> list[ProcessedIntent]:
    state = load_pending_state(session)
    active = state.active
    if active is None:
        return [_REJECTED_INTENT.model_copy()]
    if active.status != "ready":
        if (
            active.handler == "agregar_producto"
            and active.status == "pending_resolution"
        ):
            resolved = resolve_context_type(active)
            if resolved is not None:
                session.context_type = resolved.value
            return [active.model_copy()]
        return [active.model_copy(update={"status": "rejected"})]

    results: list[ProcessedIntent] = []
    while active is not None and active.status == "ready":
        if active.handler == "agregar_producto":
            result = execute_agregar_producto(db, session, active)
        elif active.handler == "quitar_producto":
            result = execute_quitar_producto(db, session, active)
        elif active.handler == "modificar_producto":
            result = execute_modificar_producto(db, session, active)
        else:
            result = active.model_copy(update={"status": "rejected"})

        results.append(result)
        if result.status == "failed":
            return results
        if result.status not in ("executed", "rejected"):
            return results
        if active.handler != "agregar_producto":
            clear_pending_context(session)
            session.context_type = None
            return results

        state = remove_active(session)
        active = state.active
        if active is None:
            clear_pending_context(session)
            session.context_type = None
            return results
        if active.handler != "agregar_producto":
            clear_pending_context(session)
            session.context_type = None
            return results
        if active.status == "pending_resolution":
            results.append(active.model_copy())
            resolved = resolve_context_type(active)
            if resolved is not None:
                session.context_type = resolved.value
            return results

    return results


__all__ = ["execute_ready_pending_context"]
