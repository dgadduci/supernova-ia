"""Vaciar pedido handler.

Consumes a ready ``vaciar_pedido`` ``ProcessedIntent`` produced by the
deterministic confirmation resolver, revalidates the session-owned
draft pedido immediately before mutation, and delegates the atomic
all-lines deletion to the transaction-neutral
``PedidoProductoService.clear_pedido_lines``.

Outcome matrix:

* ``confirmacion=False`` → rejected, reason ``"cancelled"``. No
  mutation. The pending context is cleared by the outer primitive
  (non-``agregar_producto`` branch in ``execute_ready_pending_context``).
* ``confirmacion=True`` and the revalidation passes → executed. The
  service stages the deletion of every ``PedidoProducto`` row in the
  caller's transaction; the outer transactional processor commits
  the whole turn atomically.
* ``confirmacion=True`` and the revalidation fails (missing pedido,
  session mismatch, non-borrador, empty draft, or stale state) →
  rejected with the corresponding deterministic reason. No mutation.
* Any database exception raised by the service propagates unchanged
  so the existing outer transactional owner rolls the entire turn
  back. The handler NEVER commits, rolls back, flushes, refreshes,
  begins, expires, or closes the session.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import EstadoPedido, Pedido
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import (
    PedidoNotFound,
    PedidoProductoNotEditable,
)
from backend.services.pedido_producto_service import PedidoProductoService


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def _rejected(
    intent: ProcessedIntent,
    reason: str,
) -> ProcessedIntent:
    resolved_data = dict(intent.resolved_data or {})
    resolved_data["reason"] = reason
    return intent.model_copy(
        update={"status": "rejected", "resolved_data": resolved_data}
    )


def execute_vaciar_pedido(
    db: DatabaseSession,
    conversation_session: ConversationSession,
    intent: ProcessedIntent,
) -> ProcessedIntent:
    if (
        intent.intent != "vaciar_pedido"
        or intent.status != "ready"
        or intent.handler != "vaciar_pedido"
    ):
        return _with_status(intent, "rejected")

    confirmacion = intent.resolved_data.get("confirmacion")
    if isinstance(confirmacion, bool) and confirmacion is False:
        return _rejected(intent, "cancelled")
    if confirmacion is not True:
        return _with_status(intent, "rejected")

    pedido_id_raw = conversation_session.id_pedido
    if pedido_id_raw is None:
        return _rejected(intent, "no_draft")

    try:
        pedido_id = int(pedido_id_raw)
    except (TypeError, ValueError):
        return _rejected(intent, "no_draft")

    pedido: Pedido | None = db.get(Pedido, pedido_id)
    if pedido is None:
        return _rejected(intent, "no_draft")

    session_id = getattr(conversation_session, "id", None)
    if session_id is None or int(pedido.id_session) != int(session_id):
        return _rejected(intent, "session_mismatch")

    if pedido.estado_pedido != EstadoPedido.BORRADOR:
        return _rejected(intent, "pedido_not_borrador")

    lineas = PedidoProductoService(db).list_by_pedido(pedido_id)
    if not lineas:
        return _rejected(intent, "empty_draft")

    try:
        lineas_eliminadas = PedidoProductoService(db).clear_pedido_lines(
            pedido_id
        )
    except PedidoNotFound:
        return _rejected(intent, "no_draft")
    except PedidoProductoNotEditable:
        return _rejected(intent, "pedido_not_borrador")

    resolved_data = dict(intent.resolved_data or {})
    resolved_data["pedido_id"] = int(pedido_id)
    resolved_data["lineas_eliminadas"] = int(lineas_eliminadas)
    resolved_data["confirmacion"] = True
    resolved_data.pop("reason", None)
    return intent.model_copy(
        update={"status": "executed", "resolved_data": resolved_data}
    )


__all__ = ["execute_vaciar_pedido"]
