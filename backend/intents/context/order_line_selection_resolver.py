"""Order-line selection resolver.

Refines an active `quitar_producto` `pending_resolution` intent when the
customer replies with a more specific order-line identifier (size, product
name, etc.). Restricts the refinement strictly to the current
`candidate_ids` (no broadening back to the commerce catalog) and never
mutates `session`, the pedido, or any persisted state.

When the refinement narrows to exactly one candidate, populates
`resolved_data["pedido_producto_id"]`, sets `status="ready"`, and lets the
existing ready-execution path dispatch the handler. When the refinement
yields several candidates, sets `status="pending_resolution"` with the
reduced `candidate_ids`. When the message resolves to a `pedido_producto_id`
not in the current candidate set, returns `rejected` without mutating the
pedido.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import NoopDiagnosticSink, ResolverCallCompleted, ResolverCallStarted
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _flatten_pedido_producto_ids(recognized: dict) -> list[int]:
    ids: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pp_id = entry.get("pedido_producto_id")
        if pp_id is not None:
            ids.append(int(pp_id))
    for group in recognized.get("encontrados_posibles") or []:
        for product in group.get("productos") or []:
            pp_id = product.get("pedido_producto_id")
            if pp_id is not None:
                ids.append(int(pp_id))
    return ids


def _build_ready_intent(
    active_intent: ProcessedIntent,
    pedido_producto_id: int,
) -> ProcessedIntent:
    new_requirements = [
        RequirementState(
            name="pedido_producto_id",
            status="completed",
            value=pedido_producto_id,
        ),
    ]
    req_cant = next(
        (r for r in active_intent.requirements if r.name == "cantidad"),
        RequirementState(name="cantidad", status="pending", value=None),
    )
    new_requirements.append(req_cant)

    resolved_data = {
        **active_intent.resolved_data,
        "pedido_producto_id": pedido_producto_id,
    }
    if req_cant.value is not None and "cantidad" not in active_intent.resolved_data:
        resolved_data["cantidad"] = req_cant.value

    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="ready",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        resolved_data=resolved_data,
        requirements=new_requirements,
        candidate_ids=[],
    )


def resolve_order_line_selection(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
) -> ProcessedIntent:
    """Refine an active `quitar_producto` pending_resolution intent."""
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    started = ResolverCallStarted(
        resolver_class=type(active_intent).__name__,
        resolver_method="resolve_order_line_selection",
        resolver_purpose="order_line_refinement",
        session_id=getattr(session, "id", None),
        incoming_text=message,
        normalized_text=message,
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        quantity=(active_intent.resolved_data or {}).get("cantidad"),
        status_before=active_intent.status,
        requirements_before=list(active_intent.requirements),
        resolved_data_before=dict(active_intent.resolved_data or {}),
        candidate_ids_before=list(active_intent.candidate_ids),
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        if (
            active_intent.status != "pending_resolution"
            or not active_intent.candidate_ids
        ):
            return active_intent

        recognized = recognize_quitar_producto(db, session, message)
        recognized_ids = _flatten_pedido_producto_ids(recognized)

        if not recognized_ids:
            return active_intent

        intersection = sorted(
            set(int(cid) for cid in recognized_ids)
            & set(int(cid) for cid in active_intent.candidate_ids)
        )

        if not intersection:
            return active_intent.model_copy(update={"status": "rejected"})

        if len(intersection) == 1:
            return _build_ready_intent(active_intent, intersection[0])

        return active_intent.model_copy(update={"candidate_ids": intersection})
    finally:
        completed = ResolverCallCompleted(
            result_type=type(active_intent).__name__,
            status_after=active_intent.status,
            quantity_after=(active_intent.resolved_data or {}).get("cantidad"),
            requirements_after=list(active_intent.requirements),
            resolved_data_after=dict(active_intent.resolved_data or {}),
            candidate_ids_after=list(active_intent.candidate_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_order_line_selection"]