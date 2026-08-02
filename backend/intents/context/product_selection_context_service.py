from sqlalchemy.orm import Session

from backend.diagnostics import NoopDiagnosticSink
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.context.product_selection_context_resolver import resolve_product_selection
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.services.producto_query_service import ProductoQueryService


class ProductSelectionContextService:
    def __init__(self, session: Session, *, sink: DiagnosticSink | None = None) -> None:
        self._catalog_service = ProductoQueryService(session)
        self._sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()

    def resolve(
        self,
        message: str,
        active_intent: ProcessedIntent,
        *,
        resolver_purpose: str = "pending_context_resolution",
    ) -> ProcessedIntent:
        if active_intent.status != "pending_resolution" or not active_intent.candidate_ids:
            return active_intent
        catalog = self._catalog_service.list_presentaciones_by_ids(
            active_intent.candidate_ids
        )
        return resolve_product_selection(
            message,
            active_intent,
            catalog,
            sink=self._sink,
            resolver_purpose=resolver_purpose,
        )


__all__ = ["ProductSelectionContextService"]
