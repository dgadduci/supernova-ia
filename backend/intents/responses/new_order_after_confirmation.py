"""Deterministic Spanish response builder for `iniciar_pedido`.

Renders a single fixed `CustomerResponse` for every
`ProcessedIntent.status` outcome produced by
`backend.intents.orchestration.new_order_after_confirmation`. No LLM,
no prompt construction, no technical detail, no DB IDs in the rendered
message. The success message confirms a fresh empty order and invites
products. The rejected cases mirror the authoritative non-mutating
outcomes decided by the orchestrator.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

_SUCCESS_MESSAGE = (
    "Listo, empezamos un pedido nuevo. Decime qué productos querés agregar."
)
_DRAFT_CONTINUE_MESSAGE = (
    "Ya tenés un pedido en curso. Seguí agregando productos o confirmalo."
)
_NO_PEDIDO_MESSAGE = "Todavía no hay un pedido asociado para iniciar uno nuevo."
_FAILED_MESSAGE = (
    "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
)


def build_iniciar_pedido_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "iniciar_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "executed":
        return CustomerResponse(
            message=_SUCCESS_MESSAGE,
            intent="iniciar_pedido",
            status="executed",
        )

    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "pedido_borrador_activo":
            message = _DRAFT_CONTINUE_MESSAGE
        elif reason in ("no_pedido_asociado", "session_not_active"):
            message = _NO_PEDIDO_MESSAGE
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent="iniciar_pedido",
            status="rejected",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="iniciar_pedido",
            status="failed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="iniciar_pedido",
        status=intent.status,
    )


__all__ = ["build_iniciar_pedido_response"]
