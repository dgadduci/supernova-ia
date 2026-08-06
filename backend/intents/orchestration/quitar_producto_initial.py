"""Initial orchestration for `quitar_producto`.

Loads the active draft Pedido's order lines through the existing service
layer, runs the `quitar_producto` recognizer against them, and produces a
`ProcessedIntent` with one of three outcomes:
- `ready` (single unique match; auto-executes through the existing handler)
- `pending_resolution` (multiple candidates; persists a pending context)
- `rejected` (no candidates or no active draft pedido; no mutation)

The orchestrator never commits, rolls back, flushes, closes the SQLAlchemy
session, or generates a customer-facing response.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.handlers.quitar_producto_handler import execute_quitar_producto
from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _flatten_candidate_ids(recognized: dict) -> list[int]:
    """Flatten the recognizer's output into a list of `pedido_producto_id` values."""
    candidates: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pp_id = entry.get("pedido_producto_id")
        if pp_id is not None:
            candidates.append(int(pp_id))
    for group in recognized.get("encontrados_posibles") or []:
        if group.get("kind") == "category":
            continue
        for product in group.get("productos") or []:
            pp_id = product.get("pedido_producto_id")
            if pp_id is not None:
                candidates.append(int(pp_id))
    return candidates


def _build_requirements(
    pedido_producto_id: int | None,
    cantidad: int | None,
) -> list[RequirementState]:
    req_pp = RequirementState(
        name="pedido_producto_id",
        status="completed" if pedido_producto_id is not None else "pending",
        value=pedido_producto_id,
    )
    req_cant = RequirementState(
        name="cantidad",
        status="completed" if cantidad is not None else "pending",
        value=cantidad,
    )
    return [req_pp, req_cant]


def _build_ready_intent(
    source_text: str,
    pedido_producto_id: int,
    cantidad: int | None,
) -> ProcessedIntent:
    resolved_data: dict = {"pedido_producto_id": pedido_producto_id}
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    return ProcessedIntent(
        intent="quitar_producto",
        source_text=source_text,
        status="ready",
        recognizer="recognizer_quitar_producto",
        handler="quitar_producto",
        resolved_data=resolved_data,
        requirements=_build_requirements(pedido_producto_id, cantidad),
        candidate_ids=[],
    )


def _build_pending_intent(
    source_text: str,
    candidate_ids: list[int],
    cantidad: int | None,
) -> ProcessedIntent:
    resolved_data: dict = {}
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    return ProcessedIntent(
        intent="quitar_producto",
        source_text=source_text,
        status="pending_resolution",
        recognizer="recognizer_quitar_producto",
        handler="quitar_producto",
        resolved_data=resolved_data,
        requirements=_build_requirements(None, cantidad),
        candidate_ids=list(candidate_ids),
    )


def _build_rejected_intent(source_text: str) -> ProcessedIntent:
    return ProcessedIntent(
        intent="quitar_producto",
        source_text=source_text,
        status="rejected",
        recognizer="recognizer_quitar_producto",
        handler="quitar_producto",
    )


def process_initial_quitar_producto(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Resolve a single `quitar_producto` message to a `ProcessedIntent`.

    The function:
    - returns `rejected` (no mutation) when `session.id_pedido` is `None`;
    - loads order lines through `PedidoProductoService.list_by_pedido` (never
      running SQLAlchemy queries directly);
    - calls `recognize_quitar_producto` to obtain order-line candidates and
      an optional quantity;
    - returns `ready` (auto-executed through the existing handler) when there
      is exactly one unique candidate;
    - returns `pending_resolution` (with `candidate_ids` populated) when there
      are multiple candidates and persists a pending context of type
      `order_line_selection` so the next message is routed through the
      order-line resolver;
    - returns `rejected` (no pending context) when the recognizer surfaces no
      candidates or the draft pedido has zero order lines.
    """
    if session.id_pedido is None:
        return _build_rejected_intent(source_text)

    recognized = recognize_quitar_producto(db, session, source_text)
    candidate_ids = _flatten_candidate_ids(recognized)
    cantidad = recognized.get("cantidad")

    unique_candidate_ids = sorted(set(candidate_ids))

    if len(unique_candidate_ids) == 1:
        pedido_producto_id = unique_candidate_ids[0]
        ready_intent = _build_ready_intent(source_text, pedido_producto_id, cantidad)
        return execute_quitar_producto(db, session, ready_intent)

    if len(unique_candidate_ids) > 1:
        pending_intent = _build_pending_intent(
            source_text, unique_candidate_ids, cantidad
        )
        if resolve_context_type(pending_intent) is not None:
            set_pending_intent(session, pending_intent)
        return pending_intent

    return _build_rejected_intent(source_text)


__all__ = ["process_initial_quitar_producto"]