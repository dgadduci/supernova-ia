from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

_FAILED_MESSAGE = "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
_NO_ORDER_MESSAGE = "No tenés un pedido activo para consultar."
_STATE_MESSAGES = {
    "borrador": "Tu pedido todavía se está armando y aún no fue confirmado.",
    "ingresado": "Tu pedido fue recibido y está confirmado.",
    "preparacion": "Tu pedido confirmado está en preparación.",
    "terminado": "Tu pedido está terminado y listo.",
    "entregado": "Tu pedido figura como entregado.",
    "cancelado": "Tu pedido figura como cancelado.",
}


def build_order_status_query_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    del db, session
    if intent.intent != "consultar_estado_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    if intent.status == "rejected":
        return CustomerResponse(
            message=_NO_ORDER_MESSAGE,
            intent="consultar_estado_pedido",
            status="rejected",
        )
    if intent.status == "executed":
        state = intent.resolved_data.get("estado_pedido")
        message = _STATE_MESSAGES.get(state, _FAILED_MESSAGE)
        return CustomerResponse(
            message=message,
            intent="consultar_estado_pedido",
            status="executed" if state in _STATE_MESSAGES else "failed",
        )
    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="consultar_estado_pedido",
        status=intent.status,
    )


__all__ = ["build_order_status_query_response"]
