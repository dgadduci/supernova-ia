import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.orchestration import (
    incoming_message_orchestrator as orchestrator_module,
)
from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.llm.query_llm import QueryLlmError


def _session(context_type):
    session = MagicMock(name="ConversationSession")
    session.context_type = context_type
    return session


class ProcessIncomingMessageInitialBranchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_none_context_routes_to_initial_dispatcher(
        self, initial_dispatcher, pending_dispatcher
    ):
        sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        initial_dispatcher.return_value = [sentinel]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = process_incoming_message(db, session, "quiero una empanada")

        initial_dispatcher.assert_called_once_with(db, session, "quiero una empanada")
        pending_dispatcher.assert_not_called()
        self.assertEqual(result, [sentinel])

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_branch_preserves_multi_item_order(
        self, initial_dispatcher, pending_dispatcher
    ):
        intent_a = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        intent_b = ProcessedIntent(
            intent="desconocida",
            source_text="asdf",
            status="rejected",
            recognizer="intent_classifier",
            handler="desconocida",
        )
        initial_dispatcher.return_value = [intent_a, intent_b]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = process_incoming_message(db, session, "mix")

        self.assertEqual(len(result), 2)
        self.assertIs(result[0], intent_a)
        self.assertIs(result[1], intent_b)
        pending_dispatcher.assert_not_called()


class ProcessIncomingMessagePendingBranchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_product_selection_context_routes_to_pending_dispatcher(
        self, initial_dispatcher, pending_dispatcher
    ):
        sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="la segunda",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        pending_dispatcher.return_value = [sentinel]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        result = process_incoming_message(db, session, "la segunda")

        pending_dispatcher.assert_called_once_with(db, session, "la segunda")
        initial_dispatcher.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], sentinel)

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_other_non_none_context_type_routes_to_pending_dispatcher(
        self, initial_dispatcher, pending_dispatcher
    ):
        sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="lo otro",
            status="rejected",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        pending_dispatcher.return_value = [sentinel]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="some_other_context")

        result = process_incoming_message(db, session, "lo otro")

        pending_dispatcher.assert_called_once_with(db, session, "lo otro")
        initial_dispatcher.assert_not_called()
        self.assertEqual(result, [sentinel])


class ProcessIncomingMessageErrorPropagationTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_pending_dispatcher_sentinel_error_propagates(
        self, initial_dispatcher, pending_dispatcher
    ):
        class _SentinelError(RuntimeError):
            pass

        pending_dispatcher.side_effect = _SentinelError("boom")

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        with self.assertRaises(_SentinelError) as ctx:
            process_incoming_message(db, session, "cualquier cosa")
        self.assertIsInstance(ctx.exception, _SentinelError)
        initial_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_dispatcher_type_error_propagates(
        self, initial_dispatcher, pending_dispatcher
    ):
        initial_dispatcher.side_effect = TypeError("bad type")

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(TypeError):
            process_incoming_message(db, session, "hola")
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_dispatcher_value_error_propagates(
        self, initial_dispatcher, pending_dispatcher
    ):
        initial_dispatcher.side_effect = ValueError("bad value")

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(ValueError):
            process_incoming_message(db, session, "hola")
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_dispatcher_query_llm_error_propagates(
        self, initial_dispatcher, pending_dispatcher
    ):
        initial_dispatcher.side_effect = QueryLlmError("llm failure")

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(QueryLlmError):
            process_incoming_message(db, session, "hola")
        pending_dispatcher.assert_not_called()


class ProcessIncomingMessageValidationTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_none_message_raises_type_error(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(TypeError):
            process_incoming_message(db, session, None)  # type: ignore[arg-type]
        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_int_message_raises_type_error(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(TypeError):
            process_incoming_message(db, session, 123)  # type: ignore[arg-type]
        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_list_message_raises_type_error(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(TypeError):
            process_incoming_message(db, session, ["hola"])  # type: ignore[arg-type]
        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_none_message_raises_type_error_on_pending_branch(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        with self.assertRaises(TypeError):
            process_incoming_message(db, session, None)  # type: ignore[arg-type]
        pending_dispatcher.assert_not_called()
        initial_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_empty_message_raises_value_error(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(ValueError):
            process_incoming_message(db, session, "")
        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_whitespace_only_message_raises_value_error(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        with self.assertRaises(ValueError):
            process_incoming_message(db, session, "   ")
        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_whitespace_only_message_raises_value_error_on_pending_branch(
        self, initial_dispatcher, pending_dispatcher
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        with self.assertRaises(ValueError):
            process_incoming_message(db, session, "\n\t")
        pending_dispatcher.assert_not_called()
        initial_dispatcher.assert_not_called()


class ProcessIncomingMessagePersistenceTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_branch_does_not_commit_or_rollback(
        self, initial_dispatcher, pending_dispatcher
    ):
        initial_dispatcher.return_value = [
            ProcessedIntent(
                intent="agregar_producto",
                source_text="x",
                status="ready",
                recognizer="recognizer_productos",
                handler="agregar_producto",
            )
        ]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        process_incoming_message(db, session, "quiero una empanada")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_pending_branch_does_not_commit_or_rollback(
        self, initial_dispatcher, pending_dispatcher
    ):
        pending_dispatcher.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        process_incoming_message(db, session, "la primera")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class ProcessIncomingMessageBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(orchestrator_module)
        module = orchestrator_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "import twilio",
            "from twilio",
            "from sqlalchemy.select",
            "from sqlalchemy.orm.selectinload",
            "from backend.repositories",
            "from backend.routers",
            "from backend.sessions",
            "backend.old_project",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            orchestrator_module.__all__, ["process_incoming_message"]
        )

    def test_module_has_no_additional_public_functions(self):
        import ast

        with open(orchestrator_module.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(function_names, ["process_incoming_message"])


class ProcessIncomingMessageSequentialQueueTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_two_intents_returns_only_active_outcome(
        self, initial_dispatcher, pending_dispatcher
    ):
        """Initial dispatch with two pending active results must yield
        only one outcome to the orchestrator when Pizza is queued behind
        the active Carne clarification.
        """
        active = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        initial_dispatcher.return_value = [active]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = process_incoming_message(
            db, session,
            "quiero una empanada de carne y una pizza de muzarela",
        )

        self.assertEqual(result, [active])
        initial_dispatcher.assert_called_once()
        pending_dispatcher.assert_not_called()

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_initial_one_ready_then_one_pending_returns_both_in_order(
        self, initial_dispatcher, pending_dispatcher
    ):
        """Initial dispatch with `ready A` then `pending B` returns both
        A.executed and B.pending_resolution. """
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza chica",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        initial_dispatcher.return_value = [executed, pending]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = process_incoming_message(
            db, session,
            "pizza lista y empanada por favor",
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], executed)
        self.assertEqual(result[1], pending)

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_clarification_message_routes_to_pending_dispatcher_without_classifier(
        self, initial_dispatcher, pending_dispatcher
    ):
        """While `session.context_type` identifies an active pending
        interaction, an incoming clarification is routed through pending
        dispatch and never invokes the initial classifier."""
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="picante",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        promoted = ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[201, 202],
        )
        pending_dispatcher.return_value = [executed, promoted]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        result = process_incoming_message(db, session, "picante")

        pending_dispatcher.assert_called_once_with(db, session, "picante")
        initial_dispatcher.assert_not_called()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], executed)
        self.assertEqual(result[1], promoted)


class ProcessIncomingMessageClarificationOnlyCarnePicanteTest(unittest.TestCase):
    """5.1/5.2/5.3: orchestration guarantees for the resolved Carne
    Picante + promoted Pizza scenario.

    `picante` while Carne is active and Pizza queued must bypass initial
    classification, return the pending dispatcher's complete ordered
    list unchanged (Carne executed first, Pizza clarification second),
    and never duplicate or repeat Carne or surface an inactive queued
    clarification."""

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_picante_bypasses_classifier_and_returns_complete_list(
        self, initial_dispatcher, pending_dispatcher
    ):
        carne_executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada de carne",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 11, "cantidad": 1},
        )
        pizza_pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[201, 202],
        )
        pending_dispatcher.return_value = [carne_executed, pizza_pending]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        result = process_incoming_message(db, session, "picante")

        initial_dispatcher.assert_not_called()
        pending_dispatcher.assert_called_once_with(db, session, "picante")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], carne_executed)
        self.assertEqual(result[1], pizza_pending)

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_picante_outcome_order_carne_then_pizza_with_no_duplication(
        self, initial_dispatcher, pending_dispatcher
    ):
        carne_executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada de carne",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 11, "cantidad": 1},
        )
        pizza_pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[201, 202],
        )
        pending_dispatcher.return_value = [carne_executed, pizza_pending]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        result = process_incoming_message(db, session, "picante")

        sources = [r.source_text for r in result]
        self.assertEqual(sources.count("una empanada de carne"), 1)
        self.assertEqual(sources.count("una pizza de muzarella"), 1)
        self.assertEqual(result[0].source_text, "una empanada de carne")
        self.assertEqual(result[1].source_text, "una pizza de muzarella")
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "pending_resolution")


if __name__ == "__main__":
    unittest.main()
