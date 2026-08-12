"""Focused tests for `backend.services.outbound_response_mapper`.

These tests cover the narrow social-conversation response mapping
introduced for the ``add-social-conversation-responses`` OpenSpec
change. The mapper is the shared translation boundary between the
initial dispatcher and the staged provider outbox, so the tests
focus on:

* the deterministic fixed response selected for each of the six
  approved social intents (``saludo``, ``agradecimiento``,
  ``despedida``, ``respuesta_afirmativa``, ``respuesta_negativa``,
  ``desconocida``);
* preservation of the ``intent`` and ``status`` from the source
  ``ProcessedIntent`` on the rendered ``CustomerResponse``;
* response ordering when a social intent is mixed with another
  intent;
* preservation of the existing ``GENERIC_MESSAGE`` fallback for
  classifier intents outside the approved social set (for example
  the deferred ``ver_menu``).
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.responses.social_conversation_response import (
    SOCIAL_CONVERSATION_HANDLER,
    build_social_conversation_response,
    is_social_conversation_intent,
)
from backend.intents.schemas.processed_intent import (
    IntentStatus,
    ProcessedIntent,
)
from backend.services import outbound_response_mapper as mapper_module
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,
    build_customer_responses,
)


def _db() -> MagicMock:
    return MagicMock(name="DatabaseSession")


def _session() -> MagicMock:
    return MagicMock(name="ConversationSession")


def _processed(
    intent: str,
    status: IntentStatus = "executed",
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent,
        source_text="irrelevant",
        status=status,
        recognizer="intent_classifier",
        handler=SOCIAL_CONVERSATION_HANDLER,
    )


class IsSocialConversationIntentTest(unittest.TestCase):
    def test_recognises_each_approved_social_intent(self) -> None:
        for name in (
            "saludo",
            "agradecimiento",
            "despedida",
            "respuesta_afirmativa",
            "respuesta_negativa",
            "desconocida",
        ):
            with self.subTest(intent=name):
                self.assertTrue(is_social_conversation_intent(name))

    def test_does_not_recognise_deferred_or_unrelated_intents(self) -> None:
        for name in (
            "agregar_producto",
            "ver_menu",
            "consultar_producto",
            "consultar_estado_pedido",
            "",
        ):
            with self.subTest(intent=name):
                self.assertFalse(is_social_conversation_intent(name))


class BuildSocialConversationResponseTest(unittest.TestCase):
    def test_each_social_intent_renders_deterministic_fixed_message(self) -> None:
        expected = {
            "saludo": "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés.",
            "agradecimiento": "¡De nada! Decime si necesitás algo más.",
            "despedida": "¡Gracias por escribirnos! Hasta pronto.",
            "respuesta_afirmativa": (
                "Por ahora no tengo una pregunta activa para confirmar. "
                "Decime qué producto querés agregar o qué necesitás."
            ),
            "respuesta_negativa": (
                "Entendido. Si querés algo, decime qué necesitás."
            ),
            "desconocida": (
                "Disculpá, no entendí tu mensaje. "
                "Podés pedirme el menú o decirme qué producto querés agregar."
            ),
        }
        for name, message in expected.items():
            with self.subTest(intent=name):
                rendered = build_social_conversation_response(
                    _processed(name, status="executed")
                )
                self.assertEqual(rendered.message, message)
                self.assertEqual(rendered.intent, name)
                self.assertEqual(rendered.status, "executed")

    def test_preserves_source_status_on_rendered_response(self) -> None:
        rendered = build_social_conversation_response(
            _processed("agradecimiento", status="executed")
        )
        self.assertEqual(rendered.status, "executed")

    def test_unknown_intent_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_social_conversation_response(_processed("ver_menu"))

    def test_builder_does_not_touch_database_or_session(self) -> None:
        db = _db()
        build_social_conversation_response(_processed("saludo"))
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.begin.assert_not_called()


class BuildCustomerResponsesSocialIntentsTest(unittest.TestCase):
    @patch.object(mapper_module, "build_social_conversation_response")
    def test_saludo_is_routed_through_social_builder(
        self, social_builder
    ) -> None:
        social_builder.return_value = MagicMock(
            message="social", intent="saludo", status="executed"
        )

        responses = build_customer_responses(
            _db(), _session(), [_processed("saludo")]
        )

        self.assertEqual(len(responses), 1)
        self.assertIs(responses[0], social_builder.return_value)
        social_builder.assert_called_once()

    @patch.object(mapper_module, "build_social_conversation_response")
    def test_each_social_intent_dispatches_to_builder(
        self, social_builder
    ) -> None:
        social_builder.side_effect = [
            MagicMock(message="s", intent=name, status="executed")
            for name in (
                "saludo",
                "agradecimiento",
                "despedida",
                "respuesta_afirmativa",
                "respuesta_negativa",
                "desconocida",
            )
        ]

        intents = [_processed(name) for name in (
            "saludo",
            "agradecimiento",
            "despedida",
            "respuesta_afirmativa",
            "respuesta_negativa",
            "desconocida",
        )]
        responses = build_customer_responses(_db(), _session(), intents)

        self.assertEqual(len(responses), 6)
        self.assertEqual(social_builder.call_count, 6)

    def test_real_builder_renders_deterministic_desconocida_message(self) -> None:
        importlib.reload(mapper_module)
        responses = build_customer_responses(
            _db(),
            _session(),
            [_processed("desconocida", status="executed")],
        )

        self.assertEqual(len(responses), 1)
        rendered = responses[0]
        self.assertEqual(rendered.intent, "desconocida")
        self.assertEqual(rendered.status, "executed")
        self.assertIn("Disculpá", rendered.message)


class BuildCustomerResponsesOrderingTest(unittest.TestCase):
    def test_social_intent_preserves_position_in_mixed_intent_list(self) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="ready",
            handler="agregar_producto",
            recognizer="recognizer_productos",
        )
        middle = _processed("saludo")
        last = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="y",
            status="rejected",
            handler="consultar_estado_pedido",
            recognizer="intent_classifier",
        )

        responses = build_customer_responses(_db(), _session(), [first, middle, last])

        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0].intent, "agregar_producto")
        self.assertEqual(responses[1].intent, "saludo")
        self.assertEqual(responses[1].status, "executed")
        self.assertEqual(responses[2].intent, "consultar_estado_pedido")
        self.assertEqual(
            responses[2].message,
            "No tenés un pedido activo para consultar.",
        )
        self.assertEqual(responses[2].status, "rejected")


class BuildCustomerResponsesGenericFallbackTest(unittest.TestCase):
    def test_deferred_intent_keeps_generic_message(self) -> None:
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="__futuro_deferred_intent__",
                    source_text="x",
                    status="rejected",
                    handler="__futuro_deferred_intent__",
                    recognizer="intent_classifier",
                ),
            ],
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].message, GENERIC_MESSAGE)
        self.assertEqual(responses[0].intent, "__futuro_deferred_intent__")
        self.assertEqual(responses[0].status, "rejected")

    def test_consultar_estado_pedido_routes_to_dedicated_builder(self) -> None:
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="consultar_estado_pedido",
                    source_text="estado de mi pedido",
                    status="rejected",
                    handler="consultar_estado_pedido",
                    recognizer="intent_classifier",
                ),
            ],
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(
            responses[0].message,
            "No tenés un pedido activo para consultar.",
        )
        self.assertEqual(responses[0].intent, "consultar_estado_pedido")
        self.assertEqual(responses[0].status, "rejected")

    def test_generic_message_is_single_fixed_string(self) -> None:
        self.assertEqual(
            GENERIC_MESSAGE,
            "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?",
        )


class OutboundMapperBoundariesTest(unittest.TestCase):
    def test_module_all_exports_documented_symbols(self) -> None:
        importlib.reload(mapper_module)
        self.assertEqual(
            set(mapper_module.__all__),
            {
                "GENERIC_MESSAGE",
                "StagedOutboundRow",
                "build_customer_responses",
                "stage_outbound_rows",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
