import importlib
import traceback
import unittest
from unittest.mock import MagicMock, patch

import pydantic

from backend.intents.orchestration import (
    incoming_message_response_orchestrator as response_module,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    GENERIC_MESSAGE,
    process_incoming_message_with_responses,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.llm.query_llm import QueryLlmTimeoutError
from backend.services import outbound_response_mapper as mapper_module


def _db():
    return MagicMock(name="DatabaseSession")


def _session():
    return MagicMock(name="ConversationSession")


_SALUDO_FIXED_MESSAGE = (
    "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
)
_DESCONOCIDA_FIXED_MESSAGE = (
    "Disculpá, no entendí tu mensaje. "
    "Podés pedirme el menú o decirme qué producto querés agregar."
)


class ProcessIncomingMessageWithResponsesAgregarProductoTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_executed_status_routes_to_response_builder(
        self, inner, builder
    ):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="quiero una pizza",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 2},
        )
        inner.return_value = [processed]
        builder_response = CustomerResponse(
            message="Listo, agregué 2 Pizza Mozzarella grande.",
            intent="agregar_producto",
            status="executed",
        )
        builder.return_value = builder_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "quiero una pizza"
        )

        inner.assert_called_once_with(db, session, "quiero una pizza")
        builder.assert_called_once_with(db, session, processed)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], builder_response)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_pending_resolution_status_routes_to_response_builder(
        self, inner, builder
    ):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="quiero una pizza",
            status="pending_resolution",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
            candidate_ids=[1, 2],
        )
        inner.return_value = [processed]
        builder_response = CustomerResponse(
            message="Elegí entre: ...",
            intent="agregar_producto",
            status="pending_resolution",
        )
        builder.return_value = builder_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "quiero una pizza"
        )

        builder.assert_called_once_with(db, session, processed)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], builder_response)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_rejected_status_routes_to_response_builder(self, inner, builder):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="sin precio",
            status="rejected",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
        )
        inner.return_value = [processed]
        builder_response = CustomerResponse(
            message="No pude procesar tu pedido, ¿podrías reformularlo?",
            intent="agregar_producto",
            status="rejected",
        )
        builder.return_value = builder_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "sin precio"
        )

        builder.assert_called_once_with(db, session, processed)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], builder_response)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_failed_status_routes_to_response_builder(self, inner, builder):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="sin stock",
            status="failed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
        )
        inner.return_value = [processed]
        builder_response = CustomerResponse(
            message="Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?",
            intent="agregar_producto",
            status="failed",
        )
        builder.return_value = builder_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "sin stock"
        )

        builder.assert_called_once_with(db, session, processed)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], builder_response)


class ProcessIncomingMessageWithResponsesSocialIntentsTest(unittest.TestCase):
    """End-to-end local-path coverage for the six social intents.

    The local path now delegates to the shared response mapper, so
    each approved social intent must surface the deterministic
    Spanish response (not ``GENERIC_MESSAGE``) for the rendered
    message while preserving the source ``intent`` and ``status``.
    """

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_saludo_returns_deterministic_social_response(self, inner):
        processed = ProcessedIntent(
            intent="saludo",
            source_text="hola",
            status="executed",
            handler="social_conversation_response",
            recognizer="intent_classifier",
        )
        inner.return_value = [processed]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "hola"
        )

        self.assertEqual(len(result), 1)
        rendered = result[0]
        self.assertEqual(rendered.message, _SALUDO_FIXED_MESSAGE)
        self.assertEqual(rendered.intent, "saludo")
        self.assertEqual(rendered.status, "executed")
        self.assertNotEqual(rendered.message, GENERIC_MESSAGE)

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_desconocida_returns_deterministic_social_response(self, inner):
        processed = ProcessedIntent(
            intent="desconocida",
            source_text="asdfgh",
            status="executed",
            handler="social_conversation_response",
            recognizer="intent_classifier",
        )
        inner.return_value = [processed]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "asdfgh"
        )

        self.assertEqual(len(result), 1)
        rendered = result[0]
        self.assertEqual(rendered.message, _DESCONOCIDA_FIXED_MESSAGE)
        self.assertEqual(rendered.intent, "desconocida")
        self.assertEqual(rendered.status, "executed")
        self.assertNotEqual(rendered.message, GENERIC_MESSAGE)

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_consultar_pedido_returns_generic_response(self, inner):
        processed = ProcessedIntent(
            intent="consultar_pedido",
            source_text="estado de mi pedido",
            status="executed",
            handler="consultar_pedido",
            recognizer="intent_classifier",
            resolved_data={},
        )
        inner.return_value = [processed]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "estado de mi pedido"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].message, GENERIC_MESSAGE)
        self.assertEqual(result[0].intent, "consultar_pedido")
        self.assertEqual(result[0].status, "executed")


class ProcessIncomingMessageWithResponsesGenericMessageTest(unittest.TestCase):
    def test_generic_message_is_single_fixed_string(self):
        self.assertIsInstance(GENERIC_MESSAGE, str)
        self.assertEqual(GENERIC_MESSAGE, "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?")

    def test_generic_message_contains_no_technical_detail_tokens(self):
        for forbidden in ("id", "Exception", "Traceback", "Error"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, GENERIC_MESSAGE)

    def test_generic_message_is_non_empty(self):
        self.assertTrue(GENERIC_MESSAGE)
        self.assertGreater(len(GENERIC_MESSAGE), 0)


class ProcessIncomingMessageWithResponsesMultiIntentTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_three_intent_list_preserves_order(self, inner, builder):
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza",
            status="pending_resolution",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
            candidate_ids=[1, 2],
        )
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        social = ProcessedIntent(
            intent="desconocida",
            source_text="asdf",
            status="executed",
            handler="social_conversation_response",
            recognizer="intent_classifier",
        )
        inner.return_value = [pending, executed, social]

        clarification = CustomerResponse(
            message="CLARIFICATION",
            intent="agregar_producto",
            status="pending_resolution",
        )
        confirmation = CustomerResponse(
            message="CONFIRMATION",
            intent="agregar_producto",
            status="executed",
        )
        builder.side_effect = [clarification, confirmation]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "mix"
        )

        self.assertEqual(len(result), 3)
        self.assertIs(result[0], clarification)
        self.assertIs(result[1], confirmation)
        self.assertEqual(result[2].intent, "desconocida")
        self.assertEqual(result[2].status, "executed")
        self.assertEqual(result[2].message, _DESCONOCIDA_FIXED_MESSAGE)
        self.assertNotEqual(result[2].message, GENERIC_MESSAGE)
        self.assertEqual(builder.call_count, 2)
        builder.assert_any_call(db, session, pending)
        builder.assert_any_call(db, session, executed)


class ProcessIncomingMessageWithResponsesLengthTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_single_intent_list_returns_single_response(
        self, inner, builder
    ):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        inner.return_value = [processed]
        builder.return_value = CustomerResponse(
            message="OK",
            intent="agregar_producto",
            status="executed",
        )

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "una empanada"
        )

        self.assertEqual(len(result), 1)

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_empty_list_returns_empty_response(self, inner):
        inner.return_value = []

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "hola"
        )

        self.assertEqual(result, [])


class ProcessIncomingMessageWithResponsesExceptionPropagationTest(unittest.TestCase):
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_value_error_propagates_with_original_message(self, inner):
        sentinel = ValueError(
            "message must be a non-empty, non-whitespace string"
        )
        inner.side_effect = sentinel

        db = _db()
        session = _session()

        with self.assertRaises(ValueError) as ctx:
            process_incoming_message_with_responses(db, session, "")

        self.assertIs(ctx.exception, sentinel)
        self.assertEqual(
            str(ctx.exception),
            "message must be a non-empty, non-whitespace string",
        )

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_type_error_propagates_with_original_message(self, inner):
        sentinel = TypeError("message must be a str")
        inner.side_effect = sentinel

        db = _db()
        session = _session()

        with self.assertRaises(TypeError) as ctx:
            process_incoming_message_with_responses(db, session, None)  # type: ignore[arg-type]

        self.assertIs(ctx.exception, sentinel)
        self.assertEqual(str(ctx.exception), "message must be a str")

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_query_llm_timeout_error_propagates_with_identity(self, inner):
        sentinel = QueryLlmTimeoutError("timeout")

        with self.assertRaises(QueryLlmTimeoutError) as ctx:
            inner.side_effect = sentinel
            process_incoming_message_with_responses(
                _db(), _session(), "hola"
            )

        self.assertIs(ctx.exception, sentinel)

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_query_llm_error_propagates_with_original_traceback(
        self, inner
    ):
        sentinel = QueryLlmTimeoutError("timeout")
        inner.side_effect = sentinel

        try:
            process_incoming_message_with_responses(
                _db(), _session(), "hola"
            )
        except QueryLlmTimeoutError as exc:
            observed = exc
        else:
            self.fail("Expected QueryLlmTimeoutError to propagate")

        self.assertIs(observed, sentinel)
        self.assertIsNotNone(observed.__traceback__)
        self.assertGreaterEqual(
            len(traceback.format_exception(observed)), 1
        )

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_pydantic_validation_error_propagates_with_identity(self, inner):
        try:
            sentinel = pydantic.ValidationError.from_exception_data(
                title="Sample",
                line_errors=[
                    {
                        "type": "missing",
                        "loc": ("field",),
                        "input": None,
                    }
                ],
            )
        except TypeError:
            sentinel = pydantic.ValidationError("test", [])

        inner.side_effect = sentinel

        with self.assertRaises(pydantic.ValidationError) as ctx:
            process_incoming_message_with_responses(
                _db(), _session(), "hola"
            )

        self.assertIs(ctx.exception, sentinel)


class ProcessIncomingMessageWithResponsesPublicSurfaceTest(unittest.TestCase):
    def test_module_all_is_limited_to_response_orchestrator(self):
        importlib.reload(response_module)
        self.assertEqual(
            response_module.__all__,
            ["process_incoming_message_with_responses"],
        )

    def test_module_has_no_additional_public_functions(self):
        import ast

        with open(response_module.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(
            function_names, ["process_incoming_message_with_responses"]
        )


class ProcessIncomingMessageWithResponsesNoDatabaseMutationTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_success_path_does_not_call_db_state_methods(
        self, inner, builder
    ):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        inner.return_value = [processed]
        builder.return_value = CustomerResponse(
            message="OK",
            intent="agregar_producto",
            status="executed",
        )

        db = _db()
        session = _session()

        process_incoming_message_with_responses(db, session, "una empanada")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_exception_path_does_not_call_db_state_methods(self, inner):
        inner.side_effect = ValueError("boom")

        db = _db()
        session = _session()

        with self.assertRaises(ValueError):
            process_incoming_message_with_responses(db, session, "")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()


class ProcessIncomingMessageWithResponsesNoSessionMutationTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_agregar_producto_does_not_mutate_session_or_intent(
        self, inner, builder
    ):
        processed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        inner.return_value = [processed]
        builder.return_value = CustomerResponse(
            message="OK",
            intent="agregar_producto",
            status="executed",
        )

        db = _db()
        session = MagicMock(name="ConversationSession")
        session.pending_intents = {"k": "v"}
        session.context_type = "agregar_producto"
        session.id_pedido = 42

        pending_snapshot = dict(session.pending_intents)
        context_type_snapshot = session.context_type
        id_pedido_snapshot = session.id_pedido
        intent_snapshot = processed.model_dump()

        process_incoming_message_with_responses(db, session, "una empanada")

        self.assertEqual(session.pending_intents, pending_snapshot)
        self.assertEqual(session.context_type, context_type_snapshot)
        self.assertEqual(session.id_pedido, id_pedido_snapshot)
        self.assertEqual(processed.model_dump(), intent_snapshot)

    @patch.object(response_module, "process_incoming_message_transactional")
    def test_social_intent_does_not_mutate_session_or_intent(
        self, inner
    ):
        processed = ProcessedIntent(
            intent="desconocida",
            source_text="asdf",
            status="executed",
            handler="social_conversation_response",
            recognizer="intent_classifier",
        )
        inner.return_value = [processed]

        db = _db()
        session = MagicMock(name="ConversationSession")
        session.pending_intents = {"k": "v"}
        session.context_type = "agregar_producto"
        session.id_pedido = 42

        pending_snapshot = dict(session.pending_intents)
        context_type_snapshot = session.context_type
        id_pedido_snapshot = session.id_pedido
        intent_snapshot = processed.model_dump()

        process_incoming_message_with_responses(db, session, "asdf")

        self.assertEqual(session.pending_intents, pending_snapshot)
        self.assertEqual(session.context_type, context_type_snapshot)
        self.assertEqual(session.id_pedido, id_pedido_snapshot)
        self.assertEqual(processed.model_dump(), intent_snapshot)


class ProcessIncomingMessageWithResponsesBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(response_module)
        module = response_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        forbidden_substrings = (
            "from sqlalchemy import select",
            "joinedload",
            "from backend.repositories",
            "from backend.intents.handlers",
            "from backend.intents.context",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "from backend.intents.services",
            "from backend.llm",
            "from backend.routers",
            "from backend.dependencies",
            "from backend.sessions",
            "from backend.old_project",
            "import requests",
            "import fastapi",
            "import twilio",
            "HTTPException",
            "JSONResponse",
            "MessagingResponse",
            "QueryLlm",
            "retry",
            "backoff",
            "asyncio",
            "async def",
            "logger.",
            "logging.",
            "print(",
            "time.sleep",
        )
        for forbidden in forbidden_substrings:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_only_imports_shared_response_mapper_from_services(self):
        """The local orchestrator reuses the shared response mapper
        exactly; no other ``backend.services`` module is imported."""
        importlib.reload(response_module)
        module = response_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for allowed in (
            "from backend.services.outbound_response_mapper import",
        ):
            with self.subTest(allowed=allowed):
                self.assertIn(allowed, source)


class ProcessIncomingMessageWithResponsesCoalescingTest(unittest.TestCase):
    """Local response path applies the shared coalescing helper."""

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_two_consecutive_executed_same_id_yields_one_terminal(
        self, inner, builder
    ):
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        terminal = ProcessedIntent(
            intent="agregar_producto",
            source_text="tres empanadas",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={
                "producto_presentacion_id": 1,
                "cantidad_final": 3,
            },
        )
        inner.return_value = [first, terminal]

        terminal_response = CustomerResponse(
            message="Listo, se agregaron 3 Empanada de Carne unidad.",
            intent="agregar_producto",
            status="executed",
        )
        builder.return_value = terminal_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "tres empanadas"
        )

        self.assertEqual(len(result), 1)
        self.assertIs(result[0], terminal_response)
        builder.assert_called_once_with(db, session, terminal)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_three_consecutive_executed_same_id_yields_one_terminal(
        self, inner, builder
    ):
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 7, "cantidad": 1},
        )
        middle = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 7, "cantidad": 2},
        )
        terminal = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={
                "producto_presentacion_id": 7,
                "cantidad_final": 5,
            },
        )
        inner.return_value = [first, middle, terminal]

        terminal_response = CustomerResponse(
            message="TERMINAL",
            intent="agregar_producto",
            status="executed",
        )
        builder.return_value = terminal_response

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "x"
        )

        self.assertEqual(len(result), 1)
        self.assertIs(result[0], terminal_response)
        builder.assert_called_once_with(db, session, terminal)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_different_presentation_ids_are_not_coalesced(
        self, inner, builder
    ):
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        second = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 2, "cantidad": 1},
        )
        inner.return_value = [first, second]

        builder.side_effect = [
            CustomerResponse(
                message="FIRST",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="SECOND",
                intent="agregar_producto",
                status="executed",
            ),
        ]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "x"
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].message, "FIRST")
        self.assertEqual(result[1].message, "SECOND")
        self.assertEqual(builder.call_count, 2)
        builder.assert_any_call(db, session, first)
        builder.assert_any_call(db, session, second)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_pending_after_executed_same_id_is_not_coalesced(
        self, inner, builder
    ):
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="pending_resolution",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
            candidate_ids=[1],
        )
        inner.return_value = [executed, pending]

        builder.side_effect = [
            CustomerResponse(
                message="OK",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="CLARIFICATION",
                intent="agregar_producto",
                status="pending_resolution",
            ),
        ]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "x"
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].message, "OK")
        self.assertEqual(result[1].message, "CLARIFICATION")
        self.assertEqual(builder.call_count, 2)

    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(response_module, "process_incoming_message_transactional")
    def test_intent_change_between_same_id_is_not_coalesced(
        self, inner, builder
    ):
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        quitar = ProcessedIntent(
            intent="quitar_producto",
            source_text="y",
            status="executed",
            handler="quitar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        later = ProcessedIntent(
            intent="agregar_producto",
            source_text="z",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 3},
        )
        inner.return_value = [first, quitar, later]

        builder.side_effect = [
            CustomerResponse(
                message="ADD",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="ADD2",
                intent="agregar_producto",
                status="executed",
            ),
        ]

        db = _db()
        session = _session()

        result = process_incoming_message_with_responses(
            db, session, "x"
        )

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].message, "ADD")
        self.assertEqual(result[1].intent, "quitar_producto")
        self.assertEqual(result[2].message, "ADD2")
        self.assertEqual(builder.call_count, 2)
        builder.assert_any_call(db, session, first)
        builder.assert_any_call(db, session, later)


if __name__ == "__main__":
    unittest.main(verbosity=2)
