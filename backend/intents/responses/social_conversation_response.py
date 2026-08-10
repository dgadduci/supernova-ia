"""Pure deterministic Spanish response builder for the social conversation intents.

Renders a single fixed `CustomerResponse` for every authorized social
classifier outcome produced by
`backend.intents.orchestration.initial_intent_dispatcher` when the
session has no pending context. The builder is intentionally pure:

* It does not import the LLM, classifier, classifier prompt, session,
  database, repository or any handler / recognizer. It is a function
  over a `ProcessedIntent`.
* It does not log raw customer text or response text.
* It preserves the source `intent` and `status` verbatim on the
  returned `CustomerResponse`. The only field it replaces is the
  rendered `message`, which is taken from a fixed mapping.

The approved social intents are:

* ``saludo`` — welcome and invite an order or a concrete question.
* ``agradecimiento`` — acknowledge and offer continued help.
* ``despedida`` — brief courteous closing.
* ``respuesta_afirmativa`` — explain that no active question needs
  confirmation and invite a concrete request.
* ``respuesta_negativa`` — acknowledge and invite a concrete request.
* ``desconocida`` — contextual recovery guidance with simple order /
  menu examples.

Any other classifier intent (for example the deferred ``ver_menu``)
is intentionally NOT dispatched here; the outbound response mapper
keeps the existing ``GENERIC_MESSAGE`` fallback for those cases so a
later OpenSpec change remains the source of truth for its response.
"""
from __future__ import annotations

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent

_SALUDO_MESSAGE = (
    "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
)
_AGRADECIMIENTO_MESSAGE = (
    "¡De nada! Decime si necesitás algo más."
)
_DESPEDIDA_MESSAGE = (
    "¡Gracias por escribirnos! Hasta pronto."
)
_RESPUESTA_AFIRMATIVA_MESSAGE = (
    "Por ahora no tengo una pregunta activa para confirmar. "
    "Decime qué producto querés agregar o qué necesitás."
)
_RESPUESTA_NEGATIVA_MESSAGE = (
    "Entendido. Si querés algo, decime qué necesitás."
)
_DESCONOCIDA_MESSAGE = (
    "Disculpá, no entendí tu mensaje. "
    "Podés pedirme el menú o decirme qué producto querés agregar."
)

_SOCIAL_INTENTS: frozenset[str] = frozenset({
    "saludo",
    "agradecimiento",
    "despedida",
    "respuesta_afirmativa",
    "respuesta_negativa",
    "desconocida",
})

_SOCIAL_RESPONSES: dict[str, str] = {
    "saludo": _SALUDO_MESSAGE,
    "agradecimiento": _AGRADECIMIENTO_MESSAGE,
    "despedida": _DESPEDIDA_MESSAGE,
    "respuesta_afirmativa": _RESPUESTA_AFIRMATIVA_MESSAGE,
    "respuesta_negativa": _RESPUESTA_NEGATIVA_MESSAGE,
    "desconocida": _DESCONOCIDA_MESSAGE,
}

SOCIAL_CONVERSATION_HANDLER = "social_conversation_response"


def is_social_conversation_intent(intent_name: str) -> bool:
    """Return ``True`` when ``intent_name`` is one of the approved social intents."""
    return intent_name in _SOCIAL_INTENTS


def build_social_conversation_response(
    intent: ProcessedIntent,
) -> CustomerResponse:
    """Render the deterministic Spanish message for a social classifier intent.

    Returns a `CustomerResponse` whose ``intent`` matches the source
    ``intent.intent`` and whose ``status`` mirrors the source
    ``intent.status``. The function is pure: it never inspects the
    database, the session or any external service.
    """
    message = _SOCIAL_RESPONSES.get(intent.intent)
    if message is None:
        raise ValueError(
            f"{SOCIAL_CONVERSATION_HANDLER} does not handle intent {intent.intent!r}"
        )
    return CustomerResponse(
        message=message,
        intent=intent.intent,
        status=intent.status,
    )


__all__ = [
    "SOCIAL_CONVERSATION_HANDLER",
    "build_social_conversation_response",
    "is_social_conversation_intent",
]
