from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.sessions.enums.context_type import ContextType


def resolve_context_type(
    intent: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
    resolver_purpose: str = "initial_context_resolution",
) -> ContextType | None:
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    started = ResolverCallStarted(
        resolver_class=type(intent).__name__,
        resolver_method="resolve_context_type",
        resolver_purpose=resolver_purpose,
        intent=intent.intent,
        source_text=intent.source_text,
        quantity=(intent.resolved_data or {}).get("cantidad"),
        status_before=intent.status,
        requirements_before=list(intent.requirements),
        resolved_data_before=dict(intent.resolved_data or {}),
        candidate_ids_before=list(intent.candidate_ids),
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        if intent.status != "pending_resolution":
            return None
        if intent.intent == "modificar_producto":
            return ContextType.PRODUCT_MODIFICATION
        if intent.intent == "vaciar_pedido":
            has_pending_confirmation = any(
                req.name == "confirmacion" and req.status == "pending"
                for req in intent.requirements
            )
            if not has_pending_confirmation:
                return None
            return ContextType.ORDER_CLEAR_CONFIRMATION
        if not intent.candidate_ids:
            return None
        if intent.intent == "quitar_producto":
            return ContextType.ORDER_LINE_SELECTION
        if intent.intent == "set_observacion_producto":
            return ContextType.ORDER_LINE_SELECTION
        has_pending_pp = any(
            req.name == "producto_presentacion_id" and req.status == "pending"
            for req in intent.requirements
        )
        if not has_pending_pp:
            return None
        return ContextType.PRODUCT_SELECTION
    finally:
        completed = ResolverCallCompleted(
            result_type="ContextType",
            status_after=intent.status,
            quantity_after=(intent.resolved_data or {}).get("cantidad"),
            requirements_after=list(intent.requirements),
            resolved_data_after=dict(intent.resolved_data or {}),
            candidate_ids_after=list(intent.candidate_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_context_type"]