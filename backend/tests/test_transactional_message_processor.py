import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.orchestration import (
    transactional_message_processor as processor_module,
)
from backend.intents.orchestration.transactional_message_processor import (
    process_incoming_message_transactional,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.llm.query_llm import QueryLlmError


def _session():
    return MagicMock(name="ConversationSession")


def _db():
    return MagicMock(name="DatabaseSession")


class ProcessIncomingMessageTransactionalSuccessTest(unittest.TestCase):
    @patch.object(processor_module, "process_incoming_message")
    def test_success_path_commits_and_returns_inner_result(self, inner):
        sentinel = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        inner.return_value = [sentinel]

        db = _db()
        session = _session()
        message = "quiero una empanada"

        result = process_incoming_message_transactional(db, session, message)

        inner.assert_called_once_with(db, session, message)
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        self.assertIs(result, inner.return_value)
        self.assertEqual(result, [sentinel])


class ProcessIncomingMessageTransactionalBusinessOutcomesTest(unittest.TestCase):
    @patch.object(processor_module, "process_incoming_message")
    def test_rejected_outcome_is_committed(self, inner):
        rejected = ProcessedIntent(
            intent="desconocida",
            source_text="asdf",
            status="rejected",
            recognizer="intent_classifier",
            handler="desconocida",
        )
        expected = [rejected]
        inner.return_value = expected

        db = _db()
        session = _session()

        result = process_incoming_message_transactional(db, session, "asdf")

        inner.assert_called_once_with(db, session, "asdf")
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        self.assertIs(result, expected)

    @patch.object(processor_module, "process_incoming_message")
    def test_failed_outcome_is_committed(self, inner):
        failed = ProcessedIntent(
            intent="agregar_producto",
            source_text="sin stock",
            status="failed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        expected = [failed]
        inner.return_value = expected

        db = _db()
        session = _session()

        result = process_incoming_message_transactional(db, session, "sin stock")

        inner.assert_called_once_with(db, session, "sin stock")
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        self.assertIs(result, expected)

    @patch.object(processor_module, "process_incoming_message")
    def test_mixed_status_list_is_committed_atomically(self, inner):
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        rejected = ProcessedIntent(
            intent="desconocida",
            source_text="qzx",
            status="rejected",
            recognizer="intent_classifier",
            handler="desconocida",
        )
        failed = ProcessedIntent(
            intent="agregar_producto",
            source_text="sin stock",
            status="failed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        mixed = [executed, rejected, failed]
        inner.return_value = mixed

        db = _db()
        session = _session()

        result = process_incoming_message_transactional(db, session, "mix")

        inner.assert_called_once_with(db, session, "mix")
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        self.assertIs(result, mixed)
        self.assertEqual(len(result), 3)
        self.assertIs(result[0], executed)
        self.assertIs(result[1], rejected)
        self.assertIs(result[2], failed)


class ProcessIncomingMessageTransactionalExceptionTest(unittest.TestCase):
    @patch.object(processor_module, "process_incoming_message")
    def test_sentinel_runtime_error_rolls_back_and_re_raises(self, inner):
        class _SentinelError(RuntimeError):
            pass

        sentinel_exc = _SentinelError("boom")
        inner.side_effect = sentinel_exc

        db = _db()
        session = _session()

        with self.assertRaises(RuntimeError) as ctx:
            process_incoming_message_transactional(db, session, "hola")

        self.assertIs(ctx.exception, sentinel_exc)
        inner.assert_called_once_with(db, session, "hola")
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    @patch.object(processor_module, "process_incoming_message")
    def test_value_error_is_preserved(self, inner):
        sentinel_exc = ValueError("bad value")
        inner.side_effect = sentinel_exc

        db = _db()
        session = _session()

        with self.assertRaises(ValueError) as ctx:
            process_incoming_message_transactional(db, session, "hola")

        self.assertIs(ctx.exception, sentinel_exc)
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    @patch.object(processor_module, "process_incoming_message")
    def test_type_error_is_preserved(self, inner):
        sentinel_exc = TypeError("bad type")
        inner.side_effect = sentinel_exc

        db = _db()
        session = _session()

        with self.assertRaises(TypeError) as ctx:
            process_incoming_message_transactional(db, session, "hola")

        self.assertIs(ctx.exception, sentinel_exc)
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    @patch.object(processor_module, "process_incoming_message")
    def test_query_llm_error_is_preserved(self, inner):
        sentinel_exc = QueryLlmError("llm failure")
        inner.side_effect = sentinel_exc

        db = _db()
        session = _session()

        with self.assertRaises(QueryLlmError) as ctx:
            process_incoming_message_transactional(db, session, "hola")

        self.assertIs(ctx.exception, sentinel_exc)
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()


class ProcessIncomingMessageTransactionalNoOtherDatabaseCallsTest(unittest.TestCase):
    @patch.object(processor_module, "process_incoming_message")
    def test_success_path_does_not_call_other_session_methods(self, inner):
        inner.return_value = []

        db = _db()
        session = _session()

        process_incoming_message_transactional(db, session, "hola")

        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()

    @patch.object(processor_module, "process_incoming_message")
    def test_exception_path_does_not_call_other_session_methods(self, inner):
        inner.side_effect = RuntimeError("boom")

        db = _db()
        session = _session()

        with self.assertRaises(RuntimeError):
            process_incoming_message_transactional(db, session, "hola")

        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()


class ProcessIncomingMessageTransactionalSequentialQueueTest(unittest.TestCase):
    """Transactional regression coverage for the sequential-queue capability."""

    @patch.object(processor_module, "process_incoming_message")
    def test_successful_multi_outcome_message_commits_exactly_once(self, inner):
        """A successful multi-outcome message (one executed + one
        promoted clarification) commits the DB transaction exactly once.
        """
        executed = ProcessedIntent(
            intent="agregar_producto", source_text="empanada de carne",
            status="executed", handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        promoted = ProcessedIntent(
            intent="agregar_producto", source_text="pizza de muzarella",
            status="pending_resolution", handler="agregar_producto",
            recognizer="recognizer_productos",
            candidate_ids=[201, 202],
        )
        inner.return_value = [executed, promoted]

        db = _db()
        session = _session()

        result = process_incoming_message_transactional(
            db, session, "turno picantino"
        )

        inner.assert_called_once_with(db, session, "turno picantino")
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "pending_resolution")

    @patch.object(processor_module, "process_incoming_message")
    def test_later_handler_exception_rolls_back_full_turn(self, inner):
        """When a later promoted handler raises after an earlier mutation
        in the same HTTP request, the transactional wrapper rolls back
        exactly once and propagates the exception unchanged.
        """
        inner.side_effect = RuntimeError(
            "promoted agregar_producto handler raised"
        )

        db = _db()
        session = _session()

        with self.assertRaises(RuntimeError) as ctx:
            process_incoming_message_transactional(db, session, "msg")
        self.assertEqual(str(ctx.exception), "promoted agregar_producto handler raised")
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    @patch.object(processor_module, "process_incoming_message")
    def test_no_commit_or_rollback_for_business_rejection_outcomes(self, inner):
        """Business rejected/failed outcomes must not artificially commit
        because they come back through `process_incoming_message`. The
        transactional wrapper commits on the success path."""
        rejected = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="rejected", handler="agregar_producto",
            recognizer="recognizer_productos",
        )
        inner.return_value = [rejected]

        db = _db()
        session = _session()

        process_incoming_message_transactional(db, session, "msg")

        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()


class ProcessIncomingMessageTransactionalPublicSurfaceTest(unittest.TestCase):
    def test_module_all_is_limited_to_processor(self):
        importlib.reload(processor_module)
        self.assertEqual(
            processor_module.__all__,
            ["process_incoming_message_transactional"],
        )

    def test_module_has_no_additional_public_functions(self):
        import ast

        with open(processor_module.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(
            function_names, ["process_incoming_message_transactional"]
        )


if __name__ == "__main__":
    unittest.main()