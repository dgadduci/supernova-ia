"""Initial orchestration for `vaciar_pedido`.

The authoritative initial classifier emits `vaciar_pedido` only when the
customer requests to empty the active draft Pedido. The orchestrator:

* returns ``rejected`` (no mutation, no pending context) when the
  session has no associated pedido, the pedido belongs to a different
  session, the pedido is not in ``borrador`` state, or the pedido has
  zero ``PedidoProducto`` lines;
* otherwise persists a single ``pending_resolution`` ``vaciar_pedido``
  intent with a pending ``confirmacion`` requirement, no candidate
  ids, and a recognizer/handler pair of ``vaciar_pedido``. The
  pending context type resolves to ``order_clear_confirmation`` so the
  next customer message is routed through the dedicated confirmation
  resolver before any initial classification runs.

The orchestrator never commits, rolls back, flushes, refreshes, begins,
expires, or closes the SQLAlchemy session, and never generates a
customer-facing response.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models import EstadoPedido, Pedido
from backend.models.session import Session as ConversationSession
from backend.services.pedido_producto_service import PedidoProductoService

RECOGNIZER = "vaciar_pedido"
HANDLER = "vaciar_pedido"


def _rejected(
    source_text: str,
    reason: str,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent="vaciar_pedido",
        source_text=source_text,
        status="rejected",
        recognizer=RECOGNIZER,
        handler=HANDLER,
        resolved_data={"reason": reason},
    )


def _build_pending_intent(
    source_text: str,
    pedido_id: int,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent="vaciar_pedido",
        source_text=source_text,
        status="pending_resolution",
        recognizer=RECOGNIZER,
        handler=HANDLER,
        resolved_data={"pedido_id": int(pedido_id)},
        requirements=[
            RequirementState(
                name="confirmacion",
                status="pending",
                value=None,
            ),
        ],
        candidate_ids=[],
    )


def process_initial_vaciar_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Stage the ``order_clear_confirmation`` pending intent for an initial
    ``vaciar_pedido`` request, or reject it without mutating anything.
    """
    pedido_id_raw = session.id_pedido
    if pedido_id_raw is None:
        return _rejected(source_text, "no_draft")

    try:
        pedido_id = int(pedido_id_raw)
    except (TypeError, ValueError):
        return _rejected(source_text, "no_draft")

    pedido: Pedido | None = db.get(Pedido, pedido_id)
    if pedido is None:
        return _rejected(source_text, "no_draft")

    session_id = getattr(session, "id", None)
    if session_id is None:
        return _rejected(source_text, "session_mismatch")
    if int(pedido.id_session) != int(session_id):
        return _rejected(source_text, "session_mismatch")

    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(source_text, "pedido_not_borrador")

    lineas = PedidoProductoService(db).list_by_pedido(pedido_id)
    if not lineas:
        return _rejected(source_text, "empty_draft")

    pending_intent = _build_pending_intent(source_text, pedido_id)
    set_pending_intent(session, pending_intent)
    return pending_intent


__all__ = ["process_initial_vaciar_pedido"]
