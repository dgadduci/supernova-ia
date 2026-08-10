"""Vaciar pedido response builder.

Renders a single fixed Spanish ``CustomerResponse`` for every
``ProcessedIntent.status`` outcome produced by the ``vaciar_pedido``
pipeline. No LLM, no prompt construction, no technical detail, no DB
identifiers in the rendered message.

Deterministic message matrix:

* ``pending_resolution`` (initial prompt) → confirmation prompt that
  asks the customer to reply ``sí`` to confirm or ``no`` to cancel.
* ``executed`` (affirmative confirmed, lines cleared) → success.
* ``rejected`` with reason ``"cancelled"`` → cancellation.
* ``rejected`` with reason ``"no_draft"``,
  ``"session_mismatch"``, ``"pedido_not_borrador"``, or
  ``"empty_draft"`` → generic business rejection.
* ``failed`` → technical failure fallback.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

_PROMPT_MESSAGE = (
    "Tu pedido tiene productos. ¿Querés vaciarlo? "
    "Respondé sí para confirmar o no para cancelar."
)
_SUCCESS_MESSAGE = "Listo, vacié tu pedido."
_CANCELLED_MESSAGE = "Entendido, no vacié tu pedido."
_BUSINESS_REJECTION_MESSAGE = (
    "No pude vaciar tu pedido. Tu pedido no fue modificado."
)
_FAILED_MESSAGE = (
    "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
)


_BUSINESS_REJECTION_REASONS = frozenset(
    {"no_draft", "session_mismatch", "pedido_not_borrador", "empty_draft"}
)


def build_vaciar_pedido_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "vaciar_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "pending_resolution":
        return CustomerResponse(
            message=_PROMPT_MESSAGE,
            intent="vaciar_pedido",
            status="pending_resolution",
        )

    if intent.status == "executed":
        return CustomerResponse(
            message=_SUCCESS_MESSAGE,
            intent="vaciar_pedido",
            status="executed",
        )

    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "cancelled":
            message = _CANCELLED_MESSAGE
        elif reason in _BUSINESS_REJECTION_REASONS:
            message = _BUSINESS_REJECTION_MESSAGE
        else:
            message = _BUSINESS_REJECTION_MESSAGE
        return CustomerResponse(
            message=message,
            intent="vaciar_pedido",
            status="rejected",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="vaciar_pedido",
            status="failed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="vaciar_pedido",
        status=intent.status,
    )


__all__ = ["build_vaciar_pedido_response"]
