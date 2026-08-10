"""Explicit new-order session transition.

`process_initial_iniciar_pedido` is the only entry point called by the
initial dispatcher for the authoritative `iniciar_pedido` intent. It
uses exclusively the supplied session's `id_comercio`, `id_cliente`,
and `id_pedido`; it never searches for nor selects a different
session, pedido, comercio, or cliente.

Authoritative outcomes:

* Associated pedido is `borrador` → rejected, reason
  `pedido_borrador_activo`. Nothing is mutated.
* Associated pedido is `ingresado`, `preparacion`, `terminado`,
  `entregado`, or `cancelado` → executed. The supplied session is
  closed in place, one replacement active session and one empty
  `borrador` pedido are staged for the same `(id_comercio,
  id_cliente)`. No lines, payment, delivery, observaciones,
  pending state, or session context are copied.
* `session.id_pedido` is null or missing → rejected, reason
  `no_pedido_asociado`.
* `session.estado_session` is not `ACTIVA` → rejected, reason
  `session_not_active`.
* Technical exception → propagates to the existing transaction owner
  (`process_incoming_message_transactional` or
  `ProviderInboundMessageCoordinator.process_lease`) so the outer
  transaction rolls the entire turn back.

The transition never calls `commit`, `rollback`, `begin`, `close`,
`refresh`, or `expire`. It only flushes to order the close/create
writes required by the partial unique index on active
`(id_comercio, id_cliente)` sessions.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import EstadoPedido, Pedido
from backend.models.session import EstadoSession
from backend.models.session import Session as ConversationSession

RECOGNIZER = "new_order_after_confirmation"
HANDLER = "iniciar_pedido"


def _rejected(
    source_text: str,
    reason: str,
    *,
    extras: dict[str, Any] | None = None,
) -> ProcessedIntent:
    resolved_data: dict[str, Any] = {"reason": reason}
    if extras:
        resolved_data.update(extras)
    return ProcessedIntent(
        intent="iniciar_pedido",
        source_text=source_text,
        status="rejected",
        recognizer=RECOGNIZER,
        handler=HANDLER,
        resolved_data=resolved_data,
    )


def process_initial_iniciar_pedido(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Close the active session and stage a successor for a confirmed order.

    Stages ``CERRADA`` on the supplied session, flushes so the partial
    unique index on active sessions releases the row, then stages one
    new active session and one empty ``borrador`` pedido for the same
    commerce/client pair. Returns one typed ``ProcessedIntent`` whose
    ``resolved_data`` carries the successor identifiers.
    """
    if session.estado_session != EstadoSession.ACTIVA:
        return _rejected(source_text, "session_not_active")

    if session.id_pedido is None:
        return _rejected(source_text, "no_pedido_asociado")

    pedido = db.get(Pedido, int(session.id_pedido))
    if pedido is None:
        return _rejected(source_text, "no_pedido_asociado")

    if pedido.estado_pedido == EstadoPedido.BORRADOR:
        return _rejected(
            source_text,
            "pedido_borrador_activo",
            extras={
                "pedido_id": int(pedido.id),
                "session_id": int(session.id or 0) or None,
            },
        )

    comercio_id = int(session.id_comercio)
    cliente_id = int(session.id_cliente)

    session.estado_session = EstadoSession.CERRADA
    db.flush()

    successor_session = ConversationSession(
        id_comercio=comercio_id,
        id_cliente=cliente_id,
        id_pedido=None,
        estado_session=EstadoSession.ACTIVA,
        pending_intents={},
        context_type=None,
    )
    db.add(successor_session)
    db.flush()

    successor_pedido = Pedido(
        id_session=int(successor_session.id),
        id_medio_pago=None,
        id_metodo_entrega=None,
        datetime_entrega_programada=None,
        estado_pedido=EstadoPedido.BORRADOR,
    )
    db.add(successor_pedido)
    db.flush()

    successor_session.id_pedido = int(successor_pedido.id)

    return ProcessedIntent(
        intent="iniciar_pedido",
        source_text=source_text,
        status="executed",
        recognizer=RECOGNIZER,
        handler=HANDLER,
        resolved_data={
            "predecessor_session_id": int(session.id or 0) or None,
            "predecessor_pedido_id": int(pedido.id),
            "successor_session_id": int(successor_session.id),
            "successor_pedido_id": int(successor_pedido.id),
        },
    )


__all__ = ["process_initial_iniciar_pedido"]
