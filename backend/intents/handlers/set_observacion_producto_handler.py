"""Set product-line observation handler.

Consumes a ready ``set_observacion_producto`` ``ProcessedIntent``,
re-validates active session state, the local ``observation_action``
(``set`` or ``clear``) and the ``pedido_producto_id`` derived from the
order-line recognizer, and assigns the trimmed user text or ``NULL`` to
``PedidoProducto.observaciones`` through the dedicated
caller-owned ``PedidoProductoService.set_observacion_producto`` seam.

The handler:

- never queries SQLAlchemy directly;
- never broadens the candidate set, never reclassifies, never invokes
  the LLM, never paraphrases the observation text, and never shortens
  it for a clear action;
- never commits, rolls back, flushes, refreshes, expires, begins, or
  closes the database session — the new service seam performs the
  nullable assignment inside the caller's existing transaction;
- never raises HTTP errors and never catches broad ``Exception`` to
  translate it; only the documented business exceptions are mapped to
  the ``rejected`` status;
- never clears pending context or promotes queues.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import EstadoSession
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import (
    PedidoNotFound,
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
    PedidoSessionMismatch,
)
from backend.services.pedido_producto_service import PedidoProductoService


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def _enrich_executed(
    intent: ProcessedIntent,
    *,
    producto_nombre: str,
    presentacion_codigo: str,
    presentacion_descripcion: str,
    observation_action: str,
) -> dict:
    return {
        **intent.resolved_data,
        "producto_nombre": producto_nombre,
        "presentacion_codigo": presentacion_codigo,
        "presentacion_descripcion": presentacion_descripcion,
        "observation_action": observation_action,
    }


def _validate_intent_shape(intent: ProcessedIntent) -> str | None:
    if intent.intent != "set_observacion_producto":
        return "intent_mismatch"
    if intent.status != "ready":
        return "status_not_ready"
    if intent.handler != "set_observacion_producto":
        return "handler_mismatch"
    return None


def _validated_pedido_producto_id(intent: ProcessedIntent) -> int | None:
    raw = intent.resolved_data.get("pedido_producto_id")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if raw <= 0:
        return None
    return raw


def _validated_observation_action(intent: ProcessedIntent) -> str | None:
    action = intent.resolved_data.get("observation_action")
    if action == "set":
        return "set"
    if action == "clear":
        return "clear"
    return None


def _validated_observation_text(
    intent: ProcessedIntent,
    action: str,
) -> str | None:
    if action == "clear":
        return None
    text = intent.resolved_data.get("observation_text")
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    return cleaned


def execute_set_observacion_producto(
    db: DatabaseSession,
    conversation_session: ConversationSession,
    intent: ProcessedIntent,
) -> ProcessedIntent:
    """Apply a ready ``set_observacion_producto`` intent.

    The handler validates the intent shape, the active session state,
    the resolved ``pedido_producto_id`` and the local ``observation_action``
    (+ raw text for ``set``), then delegates the assignment to the
    dedicated service seam. The service performs the owner/draft/line
    validation and stages the nullable assignment without taking
    transaction ownership.
    """
    shape_error = _validate_intent_shape(intent)
    if shape_error is not None:
        return _with_status(intent, "rejected")

    pedido_producto_id = _validated_pedido_producto_id(intent)
    if pedido_producto_id is None:
        return _with_status(intent, "rejected")

    action = _validated_observation_action(intent)
    if action is None:
        return _with_status(intent, "rejected")

    observation_text = _validated_observation_text(intent, action)
    if action == "set" and observation_text is None:
        return _with_status(intent, "rejected")

    if getattr(conversation_session, "estado_session", None) != EstadoSession.ACTIVA:
        return _with_status(intent, "rejected")

    pedido_id = getattr(conversation_session, "id_pedido", None)
    if not isinstance(pedido_id, int) or isinstance(pedido_id, bool):
        return _with_status(intent, "rejected")
    if pedido_id <= 0:
        return _with_status(intent, "rejected")

    session_id = getattr(conversation_session, "id", None)
    if not isinstance(session_id, int) or isinstance(session_id, bool):
        return _with_status(intent, "rejected")
    if session_id <= 0:
        return _with_status(intent, "rejected")

    try:
        line = PedidoProductoService(db).set_observacion_producto(
            session_id=session_id,
            pedido_id=pedido_id,
            pedido_producto_id=pedido_producto_id,
            observacion=observation_text,
        )
    except (
        PedidoNotFound,
        PedidoProductoNotFound,
        PedidoProductoNotEditable,
        PedidoSessionMismatch,
    ):
        return _with_status(intent, "rejected")

    producto_presentacion = line.producto_presentacion
    presentacion = producto_presentacion.presentacion
    producto = producto_presentacion.producto

    enriched = _enrich_executed(
        intent,
        producto_nombre=producto.nombre,
        presentacion_codigo=presentacion.codigo,
        presentacion_descripcion=presentacion.descripcion,
        observation_action=action,
    )
    return intent.model_copy(
        update={"status": "executed", "resolved_data": enriched}
    )


def build_ready_requirements(
    *,
    pedido_producto_id: int,
    observation_action: str,
) -> list[RequirementState]:
    """Authoritative requirement list for a ready clarification.

    The order-line recognizer pre-resolved ``pedido_producto_id``; the
    local grammar pre-resolved the action and (for ``set``) the text.
    Both requirements are therefore completed before the handler runs.
    """
    return [
        RequirementState(
            name="pedido_producto_id",
            status="completed",
            value=pedido_producto_id,
        ),
        RequirementState(
            name="observacion",
            status="completed",
            value=observation_action,
        ),
    ]


__all__ = ["execute_set_observacion_producto"]
