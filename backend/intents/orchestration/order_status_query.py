from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.pedido import Pedido
from backend.models.session import Session as ConversationSession

_INTENT = "consultar_estado_pedido"
_RECOGNIZER = "order_status_query"
_HANDLER = _INTENT


def _rejected(
    source_text: str,
    reason: str,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=_INTENT,
        source_text=source_text,
        status="rejected",
        recognizer=_RECOGNIZER,
        handler=_HANDLER,
        resolved_data={"reason": reason},
    )


def process_initial_order_status_query(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    pedido_id = session.id_pedido
    if pedido_id is None:
        return _rejected(source_text, "no_pedido_asociado")

    pedido = db.get(Pedido, int(pedido_id))
    if pedido is None:
        return _rejected(source_text, "no_pedido_asociado")
    if pedido.id_session != session.id:
        return _rejected(source_text, "session_mismatch")

    return ProcessedIntent(
        intent=_INTENT,
        source_text=source_text,
        status="executed",
        recognizer=_RECOGNIZER,
        handler=_HANDLER,
        resolved_data={"estado_pedido": pedido.estado_pedido.value},
    )


__all__ = ["process_initial_order_status_query"]
