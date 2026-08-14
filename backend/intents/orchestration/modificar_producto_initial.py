"""Initial orchestration for `modificar_producto`.

Loads source candidates exclusively from the active draft Pedido's
`PedidoProducto` lines through the existing service layer and destination
candidates from the comercio's active and available catalog through the
existing product-query service. The orchestrator emits `ready` when both
domains resolve uniquely and the source and destination are not equivalent,
`pending_resolution` when either domain remains ambiguous (with an explicit
`stage` of `source_selection` or `destination_selection`), or `rejected` (no
pending context) when the source is absent, the destination is unavailable,
or the source equals the destination.

The orchestrator never commits, rolls back, flushes, closes the SQLAlchemy
session, or generates a customer-facing response.
"""
from typing import Literal

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.handlers.modificar_producto_handler import (
    execute_modificar_producto,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    recognize_modificar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _build_requirements(
    pedido_producto_origen_id: int | None,
    producto_presentacion_destino_id: int | None,
    cantidad: int | None,
    cantidad_destino: int | None = None,
) -> list[RequirementState]:
    return [
        RequirementState(
            name="pedido_producto_origen_id",
            status="completed" if pedido_producto_origen_id is not None else "pending",
            value=pedido_producto_origen_id,
        ),
        RequirementState(
            name="producto_presentacion_destino_id",
            status=(
                "completed"
                if producto_presentacion_destino_id is not None
                else "pending"
            ),
            value=producto_presentacion_destino_id,
        ),
        RequirementState(
            name="cantidad",
            status="completed" if cantidad is not None else "pending",
            value=cantidad,
        ),
        RequirementState(
            name="cantidad_destino",
            status=(
                "completed" if cantidad_destino is not None else "pending"
            ),
            value=cantidad_destino,
        ),
    ]


def _build_ready_intent(
    source_text: str,
    pedido_producto_origen_id: int,
    producto_presentacion_destino_id: int,
    cantidad: int | None,
    cantidad_destino: int | None = None,
) -> ProcessedIntent:
    resolved_data: dict = {
        "pedido_producto_origen_id": pedido_producto_origen_id,
        "producto_presentacion_destino_id": producto_presentacion_destino_id,
        "source_candidate_ids": [pedido_producto_origen_id],
        "destination_candidate_ids": [producto_presentacion_destino_id],
    }
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    if cantidad_destino is not None:
        resolved_data["cantidad_destino"] = cantidad_destino
    return ProcessedIntent(
        intent="modificar_producto",
        source_text=source_text,
        status="ready",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        resolved_data=resolved_data,
        requirements=_build_requirements(
            pedido_producto_origen_id,
            producto_presentacion_destino_id,
            cantidad,
            cantidad_destino,
        ),
        candidate_ids=[],
    )


def _build_pending_intent(
    source_text: str,
    stage: "Literal['source_selection', 'destination_selection']",
    source_candidate_ids: list[int],
    destination_candidate_ids: list[int],
    cantidad: int | None,
    cantidad_destino: int | None = None,
) -> ProcessedIntent:
    resolved_data: dict = {
        "source_candidate_ids": list(source_candidate_ids),
        "destination_candidate_ids": list(destination_candidate_ids),
    }
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    if cantidad_destino is not None:
        resolved_data["cantidad_destino"] = cantidad_destino
    return ProcessedIntent(
        intent="modificar_producto",
        source_text=source_text,
        status="pending_resolution",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        stage=stage,
        resolved_data=resolved_data,
        requirements=_build_requirements(None, None, cantidad, cantidad_destino),
        candidate_ids=[],
    )


def _build_rejected_intent(
    source_text: str, reason: str | None = None
) -> ProcessedIntent:
    resolved_data: dict = {}
    if reason is not None:
        resolved_data["reason"] = reason
    return ProcessedIntent(
        intent="modificar_producto",
        source_text=source_text,
        status="rejected",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        resolved_data=resolved_data,
    )


def process_initial_modificar_producto(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Resolve a single `modificar_producto` message to a `ProcessedIntent`.

    Returns:
    - `rejected` (no pending context) when `session.id_pedido` is `None`;
    - `ready` when source and destination both resolve uniquely and the
      source and destination are not equivalent;
    - `pending_resolution` with `stage="source_selection"` when the source
      remains ambiguous;
    - `pending_resolution` with `stage="destination_selection"` when the
      source is unique but the destination remains ambiguous;
    - `rejected` (no pending context) when either domain has zero candidates
      or the source equals the destination. The orchestrator distinguishes
      between source-absent and destination-absent rejection reasons so the
      response builder can render the appropriate Pedido-preserved message.
    """
    if session.id_pedido is None:
        return _build_rejected_intent(source_text)

    recognized = recognize_modificar_producto(db, session, source_text)
    source_candidate_ids = recognized.get("source_candidate_ids") or []
    destination_candidate_ids = recognized.get("destination_candidate_ids") or []
    cantidad = recognized.get("cantidad")
    cantidad_destino = recognized.get("cantidad_destino")
    cantidad_destino_invalid = bool(
        recognized.get("cantidad_destino_invalid")
    )

    # Deterministic rejection of an explicit invalid destination quantity
    # BEFORE creating pending, resolving candidates or invoking the
    # handler/service. The explicit-invalid signal is distinct from the
    # absent-quantity case so the legacy equal-quantity fallback can
    # never be triggered for a `0` or negative destination amount.
    if cantidad_destino_invalid:
        return _build_rejected_intent(
            source_text, reason="invalid_destination_quantity"
        )

    if not source_candidate_ids and not destination_candidate_ids:
        return _build_rejected_intent(source_text, reason="source_absent")
    if not source_candidate_ids:
        return _build_rejected_intent(source_text, reason="source_absent")
    if not destination_candidate_ids:
        return _build_rejected_intent(
            source_text, reason="no_destination_candidates"
        )

    if (
        len(source_candidate_ids) == 1
        and len(destination_candidate_ids) == 1
        and source_candidate_ids[0] is not None
        and destination_candidate_ids[0] is not None
    ):
        ready_intent = _build_ready_intent(
            source_text,
            int(source_candidate_ids[0]),
            int(destination_candidate_ids[0]),
            cantidad,
            cantidad_destino,
        )
        return execute_modificar_producto(db, session, ready_intent)

    if len(source_candidate_ids) > 1:
        pending_intent = _build_pending_intent(
            source_text,
            "source_selection",
            source_candidate_ids,
            destination_candidate_ids,
            cantidad,
            cantidad_destino,
        )
        set_pending_intent(session, pending_intent)
        return pending_intent

    if (
        len(source_candidate_ids) == 1
        and len(destination_candidate_ids) > 1
    ):
        pending_intent = _build_pending_intent(
            source_text,
            "destination_selection",
            source_candidate_ids,
            destination_candidate_ids,
            cantidad,
            cantidad_destino,
        )
        set_pending_intent(session, pending_intent)
        return pending_intent

    return _build_rejected_intent(source_text, reason="no_destination_candidates")


__all__ = ["process_initial_modificar_producto"]
