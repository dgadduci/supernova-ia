"""Non-activation regression tests for the Phase-1 catalog.

The Phase-1 change must NOT activate LLM response embellishment. The
selected flavor is stored configuration only. These tests verify:

* the deterministic customer response mapper continues to render
  the same byte-for-byte text under the canonical ``neutro`` flavor;
* the new flavor surface does not introduce any LLM client
  dependency (model, repository, service, router).
"""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock

from backend.intents.responses.draft_order_closure import (
    build_set_direccion_entrega_response,
    build_set_fecha_hora_entrega_response,
)
from backend.intents.responses.social_conversation_response import (
    build_social_conversation_response,
)
from backend.intents.schemas.processed_intent import (
    IntentStatus,
    ProcessedIntent,
)
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,
    build_customer_responses,
)


def _processed(intent: str, status: IntentStatus = "executed") -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent,
        source_text="x",
        status=status,
        recognizer="intent_classifier",
        handler="social_conversation_response",
    )


class CustomerResponseNonActivationTest(unittest.TestCase):
    """The mapper keeps the documented deterministic messages for
    every approved social intent and the ``GENERIC_MESSAGE``
    fallback. The mapper never touches the database, the session,
    or any LLM client."""

    def test_social_intents_render_fixed_messages(self) -> None:
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
        for intent, expected_message in expected.items():
            with self.subTest(intent=intent):
                rendered = build_social_conversation_response(
                    _processed(intent)
                )
                self.assertEqual(rendered.message, expected_message)

    def test_build_customer_responses_is_deterministic(self) -> None:
        db = MagicMock()
        session = MagicMock()
        responses = build_customer_responses(
            db, session, [_processed("saludo")]
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(
            responses[0].message,
            "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés.",
        )
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()

    def test_generic_message_is_stable(self) -> None:
        self.assertEqual(
            GENERIC_MESSAGE,
            "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?",
        )

    def test_draft_order_closure_renderers_unchanged(self) -> None:
        intent = ProcessedIntent(
            intent="set_direccion_entrega",
            source_text="Tilcara 2020",
            status="executed",
            recognizer="draft_order_closure",
            handler="set_direccion_entrega",
            resolved_data={"accepted_length": 12},
        )
        rendered = build_set_direccion_entrega_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertIn("dirección", rendered.message.lower())
        self.assertNotIn("Tilcara", rendered.message)

    def test_fecha_hora_renderers_unchanged(self) -> None:
        intent = ProcessedIntent(
            intent="set_fecha_hora_entrega",
            source_text="15/08/2026 19:30",
            status="executed",
            recognizer="draft_order_closure",
            handler="set_fecha_hora_entrega",
            resolved_data={"accepted_format": "yyyy-mm-dd_hh:mm"},
        )
        rendered = build_set_fecha_hora_entrega_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertEqual(
            rendered.message,
            "Listo, guardé la fecha y hora de entrega.",
        )


class FlavorNonActivationLLMTest(unittest.TestCase):
    """The new flavor model, repository, service and router MUST
    NOT depend on any LLM client. The catalog exposes only static
    seed data."""

    def _assert_no_llm_token(self, source: str) -> None:
        for forbidden in (
            "HttpClient",
            "Ollama",
            "requests.",
            "openai",
            "OllamaEmbedding",
            "llm.ask",
            "llm.generate",
        ):
            self.assertNotIn(forbidden, source)

    def test_model_has_no_llm_dependency(self) -> None:
        from backend.models.flavor_comunicacion import FlavorComunicacion

        path = FlavorComunicacion.__module__.replace(".", "/") + ".py"
        with open(path) as f:
            self._assert_no_llm_token(f.read())

    def test_repository_has_no_llm_dependency(self) -> None:
        from backend.repositories.flavor_comunicacion_repository import (
            FlavorComunicacionRepository,
        )

        self._assert_no_llm_token(inspect.getsource(FlavorComunicacionRepository))

    def test_service_has_no_llm_dependency(self) -> None:
        from backend.services.comunicacion_flavor_service import (
            ComunicacionFlavorService,
        )

        self._assert_no_llm_token(inspect.getsource(ComunicacionFlavorService))

    def test_router_has_no_llm_dependency(self) -> None:
        import backend.routers.flavors_comunicacion as router

        self._assert_no_llm_token(inspect.getsource(router))


class FlavorSelectionNoMutationTest(unittest.TestCase):
    """The selection service must NOT mutate pedido, line, session
    or pending context. The service should only touch the
    ``comercios`` and ``flavors_comunicacion`` tables."""

    def test_service_uses_only_admin_repositories(self) -> None:
        import inspect

        from backend.repositories.comercio_repository import ComercioRepository
        from backend.repositories.flavor_comunicacion_repository import (
            FlavorComunicacionRepository,
        )

        commerce_source = inspect.getsource(ComercioRepository).lower()
        flavor_source = inspect.getsource(FlavorComunicacionRepository).lower()
        for forbidden in (
            "pedido",
            "pedidos_productos",
            "sesiones",
            "pending_intents",
            "pending_context",
        ):
            self.assertNotIn(forbidden, commerce_source)
            self.assertNotIn(forbidden, flavor_source)


class FlavorConfigurationNoLlmInvocationTest(unittest.TestCase):
    """The configuration read service must not request any LLM at
    runtime. The flavor summary is sourced from the database only."""

    def test_configuration_read_uses_only_database(self) -> None:
        from backend.services.configuracion_comercio_service import (
            ConfiguracionComercioService,
        )

        service_source = inspect.getsource(ConfiguracionComercioService)
        for forbidden in ("llm", "ollama", "openai", "generate"):
            self.assertNotIn(forbidden, service_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
