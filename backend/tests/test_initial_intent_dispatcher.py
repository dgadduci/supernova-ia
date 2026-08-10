import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.orchestration import initial_intent_dispatcher as dispatcher_module
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent


def _build_result(*items: tuple[IntentName, str]) -> IntentClassificationResult:
    intents = [
        ClassifiedIntent(intent=name, mensaje=message) for name, message in items
    ]
    first_message = items[0][1] if items else "x"
    return IntentClassificationResult(intents=intents, mensaje=first_message)


def _session(context_type):
    session = MagicMock(name="ConversationSession")
    session.context_type = context_type
    return session


class DispatchInitialMessageHappyPathTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_agregar_producto_calls_orchestrator_with_classified_message(
        self, classifier_cls, orchestrator
    ):
        sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        orchestrator.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "una empanada")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "quiero una empanada")

        classifier_cls.assert_called_once_with()
        classifier_instance.query.assert_called_once_with("quiero una empanada")
        orchestrator.assert_called_once_with(db, session, "una empanada")
        self.assertEqual(result, [sentinel])

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_multi_intent_preserves_classifier_order(
        self, classifier_cls, orchestrator
    ):
        agregar_sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        orchestrator.return_value = agregar_sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "dos pizzas"),
            (IntentName.DESCONOCIDA, "asdf"),
            (IntentName.SALUDO, "hola"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "mix")

        self.assertEqual(len(result), 3)
        self.assertIs(result[0], agregar_sentinel)
        self.assertEqual(result[1].intent, "desconocida")
        self.assertEqual(result[1].handler, "social_conversation_response")
        self.assertEqual(result[2].intent, "saludo")
        self.assertEqual(result[2].handler, "social_conversation_response")
        orchestrator.assert_called_once_with(db, session, "dos pizzas")


class DispatchInitialMessageRejectionTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_desconocida_returns_executed_social_processed_intent(
        self, classifier_cls, orchestrator
    ):
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.DESCONOCIDA, "asdfgh")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "asdfgh")

        orchestrator.assert_not_called()
        self.assertEqual(len(result), 1)
        social = result[0]
        self.assertEqual(social.intent, "desconocida")
        self.assertEqual(social.source_text, "asdfgh")
        self.assertEqual(social.status, "executed")
        self.assertEqual(social.recognizer, "intent_classifier")
        self.assertEqual(social.handler, "social_conversation_response")
        self.assertEqual(social.resolved_data, {})
        self.assertEqual(social.requirements, [])
        self.assertEqual(social.candidate_ids, [])

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_saludo_is_handled_without_orchestrator(self, classifier_cls, orchestrator):
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.SALUDO, "hola")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "hola")

        orchestrator.assert_not_called()
        self.assertEqual(len(result), 1)
        social = result[0]
        self.assertEqual(social.intent, "saludo")
        self.assertEqual(social.source_text, "hola")
        self.assertEqual(social.status, "executed")
        self.assertEqual(social.recognizer, "intent_classifier")
        self.assertEqual(social.handler, "social_conversation_response")

    @patch.object(dispatcher_module, "process_initial_quitar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_quitar_producto_calls_orchestrator_with_classified_message(
        self, classifier_cls, orchestrator
    ):
        sentinel = ProcessedIntent(
            intent="quitar_producto",
            source_text="quita la empanada",
            status="pending_resolution",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
        )
        orchestrator.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.QUITAR_PRODUCTO, "quita la empanada")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "quita la empanada")

        classifier_instance.query.assert_called_once_with("quita la empanada")
        orchestrator.assert_called_once_with(db, session, "quita la empanada")
        self.assertEqual(result, [sentinel])

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_quitar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_quitar_producto_ready_returned_unchanged(
        self, classifier_cls, quitar_orch, agregar_orch
    ):
        sentinel = ProcessedIntent(
            intent="quitar_producto",
            source_text="quita la pizza",
            status="ready",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
        )
        quitar_orch.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.QUITAR_PRODUCTO, "quita la pizza")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "quita la pizza")

        agregar_orch.assert_not_called()
        quitar_orch.assert_called_once_with(db, session, "quita la pizza")
        self.assertEqual(result, [sentinel])

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_quitar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_quitar_producto_pending_resolution_returned_unchanged(
        self, classifier_cls, quitar_orch, agregar_orch
    ):
        sentinel = ProcessedIntent(
            intent="quitar_producto",
            source_text="quitá una pizza",
            status="pending_resolution",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
            candidate_ids=[1, 2, 3],
        )
        quitar_orch.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.QUITAR_PRODUCTO, "quitá una pizza")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "quitá una pizza")

        agregar_orch.assert_not_called()
        self.assertEqual(result, [sentinel])


class DispatchInitialMessageGuardTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_active_product_selection_context_short_circuits_to_empty(
        self, classifier_cls, orchestrator
    ):
        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        result = dispatch_initial_message(db, session, "cualquier cosa")

        self.assertEqual(result, [])
        classifier_cls.assert_not_called()
        orchestrator.assert_not_called()

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_none_context_proceeds_past_guard(self, classifier_cls, orchestrator):
        orchestrator.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "x")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "x")

        classifier_cls.assert_called_once_with()
        classifier_instance.query.assert_called_once_with("x")
        self.assertEqual(len(result), 1)


class DispatchInitialMessagePersistenceTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_dispatcher_does_not_commit_or_rollback(
        self, classifier_cls, orchestrator
    ):
        orchestrator.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "una empanada")
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        dispatch_initial_message(db, session, "quiero una empanada")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class DispatchInitialMessageBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(dispatcher_module)
        module = dispatcher_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
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
        self.assertEqual(dispatcher_module.__all__, ["dispatch_initial_message"])

    def test_module_has_no_additional_public_functions(self):
        import ast

        with open(dispatcher_module.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(function_names, ["dispatch_initial_message"])


class DispatchInitialMessageSequentialQueueTest(unittest.TestCase):
    """Cases for the active-boundary stop and FIFO queueing behavior
    described by `initial-intent-dispatcher` requirements section.
    """

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_two_pending_only_first_is_returned_second_is_queued(
        self, classifier_cls, agregar_proc
    ):
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        second = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[21, 22],
        )
        agregar_proc.side_effect = [first, second]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
            (IntentName.AGREGAR_PRODUCTO, "pizza de muzarella"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "una empanada y una pizza")

        self.assertEqual(result, [first])
        agregar_proc.assert_any_call(db, session, "empanada de carne")
        agregar_proc.assert_any_call(db, session, "pizza de muzarella")
        self.assertEqual(agregar_proc.call_count, 2)

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_ready_then_pending_returns_both_in_order(
        self, classifier_cls, agregar_proc
    ):
        ready = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza chica",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        agregar_proc.side_effect = [ready, pending]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "pizza chica"),
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "pizza chica y empanada")

        self.assertEqual(result, [ready, pending])
        agregar_proc.assert_any_call(db, session, "pizza chica")
        agregar_proc.assert_any_call(db, session, "empanada de carne")

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_pending_then_ready_returns_only_pending(
        self, classifier_cls, agregar_proc
    ):
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        ready = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza chica",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        agregar_proc.side_effect = [pending, ready]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
            (IntentName.AGREGAR_PRODUCTO, "pizza chica"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "empanada y pizza chica")

        self.assertEqual(result, [pending])
        agregar_proc.assert_any_call(db, session, "empanada de carne")
        agregar_proc.assert_any_call(db, session, "pizza chica")
        self.assertEqual(agregar_proc.call_count, 2)

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_pending_ready_pending_only_first_pending_returned(
        self, classifier_cls, agregar_proc
    ):
        pending_a = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        ready_b = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza chica",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        pending_c = ProcessedIntent(
            intent="agregar_producto",
            source_text="faina",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[31, 32],
        )
        agregar_proc.side_effect = [pending_a, ready_b, pending_c]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
            (IntentName.AGREGAR_PRODUCTO, "pizza chica"),
            (IntentName.AGREGAR_PRODUCTO, "faina"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "empanada, pizza, faina")

        self.assertEqual(result, [pending_a])
        self.assertEqual(agregar_proc.call_count, 3)

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_three_pending_only_first_in_response(
        self, classifier_cls, agregar_proc
    ):
        pending_a = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        pending_b = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[21, 22],
        )
        pending_c = ProcessedIntent(
            intent="agregar_producto",
            source_text="faina",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[31, 32],
        )
        agregar_proc.side_effect = [pending_a, pending_b, pending_c]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
            (IntentName.AGREGAR_PRODUCTO, "pizza de muzarella"),
            (IntentName.AGREGAR_PRODUCTO, "faina"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "tres cosas")

        self.assertEqual(result, [pending_a])
        self.assertEqual(agregar_proc.call_count, 3)

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_quitar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_quitar_producto_after_active_pending_is_still_returned(
        self, classifier_cls, quitar_proc, agregar_proc
    ):
        pending_first = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        quitar = ProcessedIntent(
            intent="quitar_producto",
            source_text="sacame algo",
            status="pending_resolution",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
            candidate_ids=[101],
        )
        agregar_proc.return_value = pending_first
        quitar_proc.return_value = quitar
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
            (IntentName.QUITAR_PRODUCTO, "sacame algo"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "empanada y sacame algo")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], pending_first)
        self.assertEqual(result[1], quitar)

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_inactive_clarification_for_queued_addition_is_not_added_to_response(
        self, classifier_cls, agregar_proc
    ):
        """When the first classifier fragment is ready and the second is
        pending, only the first pending (active) ends the response.
        """
        ready = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza chica",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[11, 12],
        )
        agregar_proc.side_effect = [ready, pending]
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.AGREGAR_PRODUCTO, "pizza chica"),
            (IntentName.AGREGAR_PRODUCTO, "empanada de carne"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatch_initial_message(db, session, "mixto")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ready)
        self.assertEqual(result[1], pending)


if __name__ == "__main__":
    unittest.main()
