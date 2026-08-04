"""Product modification resolver.

Refines an active `modificar_producto` `pending_resolution` intent by
narrowing source candidates first (against the current draft Pedido) and
then destination candidates (against the active catalog) without
broadening either domain back to the full Pedido or full catalog.

The resolver preserves the already-resolved source ID, the optional
`cantidad`, and the previously resolved destination data across refinement
turns. When both domains are unique, returns `ready` so the existing
ready-execution path dispatches the modificar handler.
"""
from typing import cast

from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import ProductRecognizerProtocol
from backend.services.producto_query_service import ProductoQueryService

_product_recognizer: ProductRecognizerProtocol = FuzzyProductRecognizer()
detectar_productos = _product_recognizer.recognize


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


def _flatten_producto_presentacion_ids(recognized: dict) -> list[int]:
    ids: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pid = entry.get("producto_presentacion_id")
        if pid is not None:
            ids.append(int(pid))
    for group in recognized.get("encontrados_posibles") or []:
        for product in group.get("productos") or []:
            pid = product.get("producto_presentacion_id")
            if pid is not None:
                ids.append(int(pid))
    return ids


def _build_requirements(
    source_id: int | None,
    dest_id: int | None,
    cantidad: int | None,
) -> list[RequirementState]:
    return [
        RequirementState(
            name="pedido_producto_origen_id",
            status="completed" if source_id is not None else "pending",
            value=source_id,
        ),
        RequirementState(
            name="producto_presentacion_destino_id",
            status="completed" if dest_id is not None else "pending",
            value=dest_id,
        ),
        RequirementState(
            name="cantidad",
            status="completed" if cantidad is not None else "pending",
            value=cantidad,
        ),
    ]


def _build_pending_intent(
    active_intent: ProcessedIntent,
    stage: str,
    new_resolved_data: dict,
    new_source_ids: list[int],
    new_dest_ids: list[int],
    cantidad: int | None,
) -> ProcessedIntent:
    if cantidad is not None:
        new_resolved_data["cantidad"] = cantidad
    new_resolved_data["source_candidate_ids"] = list(new_source_ids)
    new_resolved_data["destination_candidate_ids"] = list(new_dest_ids)
    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="pending_resolution",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        stage=stage,  # type: ignore[arg-type]
        resolved_data=new_resolved_data,
        requirements=_build_requirements(None, None, cantidad),
        candidate_ids=[],
    )


def _build_ready_intent(
    active_intent: ProcessedIntent,
    new_resolved_data: dict,
    source_id: int,
    dest_id: int,
    cantidad: int | None,
) -> ProcessedIntent:
    new_resolved_data["pedido_producto_origen_id"] = source_id
    new_resolved_data["producto_presentacion_destino_id"] = dest_id
    new_resolved_data["source_candidate_ids"] = [source_id]
    new_resolved_data["destination_candidate_ids"] = [dest_id]
    if cantidad is not None:
        new_resolved_data["cantidad"] = cantidad
    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="ready",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        stage=None,
        resolved_data=new_resolved_data,
        requirements=_build_requirements(source_id, dest_id, cantidad),
        candidate_ids=[],
    )


def _resolve_source_selection(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
    resolved_data: dict,
    source_candidate_ids: list[int],
    destination_candidate_ids: list[int],
    cantidad: int | None,
) -> ProcessedIntent:
    recognized = recognize_quitar_producto(db, session, message)
    recognized_pp_ids = _flatten_pedido_producto_ids(recognized)
    if not recognized_pp_ids:
        return active_intent

    intersection = sorted(
        set(int(x) for x in recognized_pp_ids)
        & set(int(x) for x in source_candidate_ids)
    )
    if not intersection:
        return active_intent.model_copy(update={"status": "rejected"})

    new_resolved_data = dict(resolved_data)

    if len(intersection) == 1:
        source_id = intersection[0]
        if len(destination_candidate_ids) == 1:
            dest_id = destination_candidate_ids[0]
            return _build_ready_intent(
                active_intent,
                new_resolved_data,
                source_id,
                dest_id,
                cantidad,
            )
        return _build_pending_intent(
            active_intent,
            "destination_selection",
            new_resolved_data,
            intersection,
            destination_candidate_ids,
            cantidad,
        )

    return _build_pending_intent(
        active_intent,
        "source_selection",
        new_resolved_data,
        intersection,
        destination_candidate_ids,
        cantidad,
    )


def _resolve_destination_selection(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
    resolved_data: dict,
    source_candidate_ids: list[int],
    destination_candidate_ids: list[int],
    cantidad: int | None,
) -> ProcessedIntent:
    catalog = ProductoQueryService(db).list_presentaciones_by_ids(
        destination_candidate_ids
    )
    if not catalog:
        return active_intent.model_copy(update={"status": "rejected"})

    recognized = cast(dict, detectar_productos(message, catalog))
    recognized_dest_ids = _flatten_producto_presentacion_ids(recognized)
    if not recognized_dest_ids:
        return active_intent

    intersection = sorted(
        set(int(x) for x in recognized_dest_ids)
        & set(int(x) for x in destination_candidate_ids)
    )
    if not intersection:
        return active_intent.model_copy(update={"status": "rejected"})

    new_resolved_data = dict(resolved_data)

    if len(intersection) == 1:
        dest_id = intersection[0]
        source_id = (
            source_candidate_ids[0]
            if source_candidate_ids
            else resolved_data.get("pedido_producto_origen_id")
        )
        if source_id is None:
            return active_intent.model_copy(update={"status": "rejected"})
        return _build_ready_intent(
            active_intent,
            new_resolved_data,
            int(source_id),
            dest_id,
            cantidad,
        )

    return _build_pending_intent(
        active_intent,
        "destination_selection",
        new_resolved_data,
        source_candidate_ids,
        intersection,
        cantidad,
    )


def resolve_product_modification(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active_intent: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
) -> ProcessedIntent:
    """Refine an active `modificar_producto` pending_resolution intent."""
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    resolved_data = dict(active_intent.resolved_data or {})
    started = ResolverCallStarted(
        resolver_class=type(active_intent).__name__,
        resolver_method="resolve_product_modification",
        resolver_purpose=(
            f"product_modification_{active_intent.stage}"
            if active_intent.stage
            else "product_modification_refinement"
        ),
        session_id=getattr(session, "id", None),
        incoming_text=message,
        normalized_text=message,
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        quantity=resolved_data.get("cantidad"),
        status_before=active_intent.status,
        requirements_before=list(active_intent.requirements),
        resolved_data_before=dict(resolved_data),
        candidate_ids_before=list(resolved_data.get("source_candidate_ids") or []),
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        if (
            active_intent.status != "pending_resolution"
            or active_intent.intent != "modificar_producto"
        ):
            return active_intent

        source_candidate_ids = list(resolved_data.get("source_candidate_ids") or [])
        destination_candidate_ids = list(
            resolved_data.get("destination_candidate_ids") or []
        )
        cantidad = resolved_data.get("cantidad")
        stage = active_intent.stage

        if not source_candidate_ids and not destination_candidate_ids:
            return active_intent

        if stage == "source_selection":
            return _resolve_source_selection(
                db,
                session,
                message,
                active_intent,
                resolved_data,
                source_candidate_ids,
                destination_candidate_ids,
                cantidad,
            )

        if stage == "destination_selection":
            return _resolve_destination_selection(
                db,
                session,
                message,
                active_intent,
                resolved_data,
                source_candidate_ids,
                destination_candidate_ids,
                cantidad,
            )

        return active_intent
    finally:
        completed = ResolverCallCompleted(
            result_type=type(active_intent).__name__,
            status_after=active_intent.status,
            quantity_after=resolved_data.get("cantidad"),
            requirements_after=list(active_intent.requirements),
            resolved_data_after=dict(active_intent.resolved_data or {}),
            candidate_ids_after=list(
                (active_intent.resolved_data or {}).get("destination_candidate_ids")
                or []
            ),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_product_modification"]
