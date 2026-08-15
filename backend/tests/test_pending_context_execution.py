import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError

from backend.intents.orchestration import (
    incoming_message_orchestrator as orchestrator_module,
)
from backend.intents.orchestration import (
    pending_context_execution as execution_module,
)
from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState


def _session(context_type: str | None = "product_selection", pending_intents=None):
    session = MagicMock(name="ConversationSession")
    session.context_type = context_type
    session.pending_intents = pending_intents if pending_intents is not None else {
        "version": 1,
        "active": {
            "intent": "agregar_producto",
            "source_text": "dos pizzas",
            "status": "ready",
            "recognizer": "recognizer_productos",
            "handler": "agregar_producto",
            "resolved_data": {"cantidad": 2},
            "requirements": [
                {"name": "producto_presentacion_id", "status": "pending", "value": None}
            ],
            "candidate_ids": [11, 22, 33],
        },
        "queue": [],
    }
    return session


def _ready_intent() -> ProcessedIntent:
    return ProcessedIntent(
        intent="agregar_producto",
        source_text="dos pizzas",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"cantidad": 2},
        requirements=[
            RequirementState(name="producto_presentacion_id", status="pending", value=None)
        ],
        candidate_ids=[11, 22, 33],
    )


class ExecuteReadyPendingContextRejectedTest(unittest.TestCase):
    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_rejected_handler_clears_pending_context_once(
        self, handler, clear_pending
    ):
        handler.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="rejected",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )
        db = MagicMock(name="DatabaseSession")
        session = _session()

        result = execute_ready_pending_context(db, session)

        handler.assert_called_once_with(db, session, _ready_intent())
        clear_pending.assert_called_once_with(session)
        self.assertEqual(session.context_type, None)
        self.assertEqual(result[0].status, "rejected")
        self.assertEqual(result[0].intent, "agregar_producto")


class ExecuteReadyPendingContextFailedTest(unittest.TestCase):
    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_failed_handler_does_not_clear_pending_context(self, handler, clear_pending):
        handler.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="failed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )
        db = MagicMock(name="DatabaseSession")
        session = _session()
        original_context_type = session.context_type
        clear_pending.reset_mock()

        result = execute_ready_pending_context(db, session)

        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, original_context_type)
        self.assertEqual(result[0].status, "failed")


class ExecuteReadyPendingContextExecutedTest(unittest.TestCase):
    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_executed_handler_still_clears_pending_context(
        self, handler, clear_pending
    ):
        handler.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )
        db = MagicMock(name="DatabaseSession")
        session = _session()

        result = execute_ready_pending_context(db, session)

        clear_pending.assert_called_once_with(session)
        self.assertEqual(session.context_type, None)
        self.assertEqual(result[0].status, "executed")


class ExecuteReadyPendingContextExceptionTest(unittest.TestCase):
    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_raised_integrity_error_propagates_unchanged(
        self, handler, clear_pending
    ):
        sentinel = IntegrityError("INSERT", {}, Exception("db boom"))
        handler.side_effect = sentinel

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with self.assertRaises(IntegrityError) as ctx:
            execute_ready_pending_context(db, session)
        self.assertIs(ctx.exception, sentinel)
        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, "product_selection")

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_raised_runtime_error_propagates_unchanged(
        self, handler, clear_pending
    ):
        sentinel = RuntimeError("unexpected handler failure")
        handler.side_effect = sentinel

        db = MagicMock(name="DatabaseSession")
        session = _session()
        original_context_type = session.context_type

        with self.assertRaises(RuntimeError) as ctx:
            execute_ready_pending_context(db, session)
        self.assertIs(ctx.exception, sentinel)
        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, original_context_type)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class RejectedRoutesNextMessageToInitialDispatcherTest(unittest.TestCase):
    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_rejected_routes_next_message_through_initial_dispatcher(
        self, initial_dispatcher, pending_dispatcher
    ):
        initial_dispatcher.return_value = [
            ProcessedIntent(
                intent="agregar_producto",
                source_text="hola",
                status="ready",
                recognizer="intent_classifier",
                handler="agregar_producto",
            )
        ]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None, pending_intents={"version": 1, "active": None, "queue": []})

        result = process_incoming_message(db, session, "hola")

        initial_dispatcher.assert_called_once_with(db, session, "hola")
        pending_dispatcher.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "agregar_producto")

    @patch.object(orchestrator_module, "dispatch_pending_context")
    @patch.object(orchestrator_module, "dispatch_initial_message")
    def test_failed_keeps_next_message_on_pending_branch(
        self, initial_dispatcher, pending_dispatcher
    ):
        pending_dispatcher.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="retry",
            status="rejected",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="product_selection")

        process_incoming_message(db, session, "retry")

        pending_dispatcher.assert_called_once_with(db, session, "retry")
        initial_dispatcher.assert_not_called()


class ExecuteReadyPendingContextBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(execution_module)
        module = execution_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "import twilio",
            "from twilio",
            "from backend.repositories",
            "from backend.routers",
            "from backend.services",
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
            "backend.old_project",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            execution_module.__all__,
            ["execute_ready_pending_context"],
        )

    def test_module_has_no_additional_public_functions(self):
        import ast

        with open(execution_module.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ]
        self.assertEqual(
            function_names, ["execute_ready_pending_context"]
        )


class ExecuteReadyPendingContextSetObservacionProductoTest(unittest.TestCase):
    """Stale pre-deploy ``set_observacion_producto`` pending intent.

    The product-line observation capability is no longer an active
    feature. A pending intent whose handler is
    ``set_observacion_producto`` is therefore invalid after the
    deployment and must be cleared on the next message without
    invoking the historic handler and without mutating a
    ``PedidoProducto`` row. The dispatcher-level helper
    :func:`backend.intents.orchestration.pending_context_dispatcher._recover_stale_product_line_observation_pending`
    is the entry point; the ready-execution path is the only one
    that touches the persisted pending state, so the
    :func:`execute_ready_pending_context` helper is also expected to
    fail closed (the dispatcher intercepts the stale state before
    the ready-execution path ever sees it)."""

    def test_execution_module_does_not_invoke_legacy_handler(self) -> None:
        from backend.intents.orchestration import (
            pending_context_execution as execution_module,
        )

        # The ready-execution helper must not invoke any legacy
        # product-line observation handler. ``execute_set_observacion_producto``
        # was removed together with the handler module; the module
        # attribute lookup below asserts that the helper never
        # re-imports the legacy handler.
        self.assertFalse(
            hasattr(execution_module, "execute_set_observacion_producto"),
            msg="stale product-line observation handler must not be "
            "imported by the ready-execution module",
        )

        db = MagicMock(name="DatabaseSession")
        session = MagicMock(name="ConversationSession")
        session.context_type = "order_line_selection"
        session.pending_intents = {
            "version": 1,
            "active": {
                "intent": "set_observacion_producto",
                "source_text": "La pizza es sin aceitunas",
                "status": "ready",
                "recognizer": "recognizer_set_observacion_producto",
                "handler": "set_observacion_producto",
                "resolved_data": {"pedido_producto_id": 10},
                "requirements": [],
                "candidate_ids": [],
            },
            "queue": [],
        }
        result = execute_ready_pending_context(db, session)
        self.assertEqual(result[0].status, "rejected")
        self.assertEqual(result[0].intent, "set_observacion_producto")


class ExecuteReadyPendingContextPromotionTest(unittest.TestCase):
    """FIFO promotion + ready draining + context-type restoration cases
    for the `pending-context-execution` capability.
    """

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_executed_active_promotes_pending_and_appends_clarification(
        self, handler, clear_pending
    ):
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        pending_intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[201, 202],
        )
        handler.side_effect = [executed]

        active = _ready_intent()
        new_state_active = pending_intent

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[_FakeState(active), _FakeState(new_state_active)],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(new_state_active),
        ):
            result = execute_ready_pending_context(db, session)

        handler.assert_called_once_with(db, session, _ready_intent())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "pending_resolution")
        self.assertEqual(result[1].source_text, "pizza de muzarella")
        self.assertEqual(session.context_type, "product_selection")
        clear_pending.assert_not_called()

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_rejected_active_promotes_pending(
        self, handler, clear_pending
    ):
        rejected = ProcessedIntent(
            intent="agregar_producto",
            source_text="empanada de carne",
            status="rejected",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        promoted = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            candidate_ids=[201, 202],
        )
        handler.side_effect = [rejected]

        active = _ready_intent()

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[_FakeState(active), _FakeState(promoted)],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(promoted),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "rejected")
        self.assertEqual(result[1].status, "pending_resolution")
        self.assertEqual(session.context_type, "product_selection")
        clear_pending.assert_not_called()

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_ready_drain_executes_each_promoted_ready_in_fifo_order(
        self, handler, clear_pending
    ):
        first_exec = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="executed", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        second_exec = ProcessedIntent(
            intent="agregar_producto", source_text="y",
            status="executed", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        handler.side_effect = [first_exec, second_exec]
        ready_a = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="ready", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        ready_b = ProcessedIntent(
            intent="agregar_producto", source_text="y",
            status="ready", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[
                _FakeState(ready_a),
                _FakeState(ready_b),
                _FakeState(None),
            ],
        ), patch.object(
            execution_module, "remove_active",
            side_effect=[
                _FakeState(ready_b),
                _FakeState(None),
            ],
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "executed")
        self.assertEqual(handler.call_count, 2)
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_failed_result_stays_active_and_stops_advancement(
        self, handler, clear_pending
    ):
        failed = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="failed", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        handler.side_effect = [failed]
        active = _ready_intent()
        next_queue = ProcessedIntent(
            intent="agregar_producto", source_text="queued",
            status="ready", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            return_value=_FakeState(active),
        ):
            result = execute_ready_pending_context(db, session)

        handler.assert_called_once_with(db, session, _ready_intent())
        self.assertEqual(result, [failed])
        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, "product_selection")
        self.assertEqual(len(next_queue.requirements), 0)
        self.assertEqual(next_queue.status, "ready")

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_quantity_and_candidate_survive_promotion(
        self, handler, clear_pending
    ):
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza cantidad 2",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"producto_presentacion_id": 99, "cantidad": 2},
        )
        promoted = ProcessedIntent(
            intent="agregar_producto",
            source_text="pizza cantidad 2",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 2},
            requirements=[],
            candidate_ids=[501, 502],
        )
        handler.side_effect = [executed]

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[_FakeState(_ready_intent()), _FakeState(promoted)],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(promoted),
        ):
            result = execute_ready_pending_context(db, session)

        promoted_in_result = result[1]
        self.assertEqual(promoted_in_result.candidate_ids, [501, 502])
        self.assertEqual(
            promoted_in_result.resolved_data.get("cantidad"), 2
        )

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_promoted_handler_exception_propagates_and_keeps_state(
        self, handler, clear_pending
    ):
        sentinel = RuntimeError("promoted handler boom")
        handler.side_effect = sentinel
        active = _ready_intent()

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            return_value=_FakeState(active),
        ), self.assertRaises(RuntimeError) as ctx:
            execute_ready_pending_context(db, session)
        self.assertIs(ctx.exception, sentinel)
        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, "product_selection")

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_finite_loop_stops_after_final_queue_exhaustion(
        self, handler, clear_pending
    ):
        exec_result = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="executed", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        handler.side_effect = [exec_result]
        ready = _ready_intent()

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[_FakeState(ready), _FakeState(None)],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(None),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_handler_called_exactly_once_for_single_queue_drain(
        self, handler, clear_pending
    ):
        exec_result = ProcessedIntent(
            intent="agregar_producto", source_text="x",
            status="executed", recognizer="recognizer_productos",
            handler="agregar_producto", resolved_data={},
            requirements=[], candidate_ids=[],
        )
        promoted = ProcessedIntent(
            intent="agregar_producto", source_text="y",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 1},
            requirements=[],
            candidate_ids=[701],
        )
        handler.side_effect = [exec_result]

        class _FakeState:
            def __init__(self, active):
                self.active = active

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[_FakeState(_ready_intent()), _FakeState(promoted)],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(promoted),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(handler.call_count, 1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1].status, "pending_resolution")


class ExecuteReadyPendingContextCarnePicanteTest(unittest.TestCase):
    """4.1, 4.2, 4.3, 4.4: execution guarantees for the resolved Carne
    Picante → promoted Pizza scenario."""

    def _carne_ready(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada de carne",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={
                "producto_presentacion_id": 11,
                "cantidad": 1,
            },
            requirements=[
                RequirementState(
                    name="producto_presentacion_id",
                    status="completed",
                    value=11,
                )
            ],
            candidate_ids=[],
        )

    def _pizza_queued(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza de muzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 1},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id",
                    status="pending",
                    value=None,
                )
            ],
            candidate_ids=[201, 202],
        )

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_carne_executes_exactly_once_and_preserves_pizza_queue(
        self, handler, clear_pending
    ):
        carne_exec = self._carne_ready().model_copy(update={"status": "executed"})
        handler.side_effect = [carne_exec]

        class _FakeState:
            def __init__(self, active, queue=None):
                self.active = active
                self.queue = queue or []

        carne_active = self._carne_ready()
        pizza_queued = self._pizza_queued()

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[
                _FakeState(carne_active, queue=[pizza_queued]),
                _FakeState(pizza_queued, queue=[]),
            ],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(pizza_queued, queue=[]),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(handler.call_count, 1)
        handler.assert_called_once_with(db, session, self._carne_ready())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(
            result[0].resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result[1].status, "pending_resolution")
        self.assertEqual(result[1].source_text, "una pizza de muzarella")

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_promoted_pizza_retains_all_persisted_fields(
        self, handler, clear_pending
    ):
        carne_exec = self._carne_ready().model_copy(update={"status": "executed"})
        handler.side_effect = [carne_exec]

        class _FakeState:
            def __init__(self, active, queue=None):
                self.active = active
                self.queue = queue or []

        carne_active = self._carne_ready()
        pizza_queued = self._pizza_queued()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "product_selection"

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[
                _FakeState(carne_active, queue=[pizza_queued]),
                _FakeState(pizza_queued, queue=[]),
            ],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(pizza_queued, queue=[]),
        ):
            result = execute_ready_pending_context(db, session)

        promoted = result[1]
        self.assertEqual(promoted.intent, "agregar_producto")
        self.assertEqual(promoted.source_text, "una pizza de muzarella")
        self.assertEqual(promoted.candidate_ids, [201, 202])
        self.assertEqual(promoted.resolved_data.get("cantidad"), 1)
        self.assertEqual(promoted.status, "pending_resolution")
        self.assertEqual(promoted.recognizer, "recognizer_productos")
        self.assertEqual(promoted.handler, "agregar_producto")
        self.assertEqual(
            [r.name for r in promoted.requirements],
            ["producto_presentacion_id"],
        )
        self.assertEqual(session.context_type, "product_selection")
        clear_pending.assert_not_called()

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_failed_handler_stops_advancement_without_queue_loss(
        self, handler, clear_pending
    ):
        failed = self._carne_ready().model_copy(update={"status": "failed"})
        handler.side_effect = [failed]

        class _FakeState:
            def __init__(self, active, queue=None):
                self.active = active
                self.queue = queue or []

        carne_active = self._carne_ready()
        pizza_queued = self._pizza_queued()

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            return_value=_FakeState(carne_active, queue=[pizza_queued]),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(handler.call_count, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "failed")
        clear_pending.assert_not_called()
        self.assertEqual(session.context_type, "product_selection")

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_rejected_handler_promotes_pizza(
        self, handler, clear_pending
    ):
        rejected = self._carne_ready().model_copy(update={"status": "rejected"})
        handler.side_effect = [rejected]

        class _FakeState:
            def __init__(self, active, queue=None):
                self.active = active
                self.queue = queue or []

        carne_active = self._carne_ready()
        pizza_queued = self._pizza_queued()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "product_selection"

        with patch.object(
            execution_module, "load_pending_state",
            side_effect=[
                _FakeState(carne_active, queue=[pizza_queued]),
                _FakeState(pizza_queued, queue=[]),
            ],
        ), patch.object(
            execution_module, "remove_active",
            return_value=_FakeState(pizza_queued, queue=[]),
        ):
            result = execute_ready_pending_context(db, session)

        self.assertEqual(handler.call_count, 1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "rejected")
        self.assertEqual(result[1].status, "pending_resolution")
        self.assertEqual(result[1].source_text, "una pizza de muzarella")
        self.assertEqual(session.context_type, "product_selection")
        clear_pending.assert_not_called()


class ExecuteReadyPendingContextTransactionalBoundaryTest(unittest.TestCase):
    """4.4: raised technical exceptions propagate unchanged and leave
    commit/rollback ownership with the transactional wrapper."""

    @patch.object(execution_module, "clear_pending_context")
    @patch.object(execution_module, "execute_agregar_producto")
    def test_value_error_propagates_without_pending_mutation(
        self, handler, clear_pending
    ):
        sentinel = ValueError("invalid intent value")
        handler.side_effect = sentinel

        db = MagicMock(name="DatabaseSession")
        session = _session()

        with patch.object(
            execution_module, "load_pending_state",
            return_value=_FakeStateLike(_ready_intent()),
        ), self.assertRaises(ValueError) as ctx:
            execute_ready_pending_context(db, session)
        self.assertIs(ctx.exception, sentinel)
        clear_pending.assert_not_called()
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class _FakeStateLike:
    def __init__(self, active, queue=None):
        self.active = active
        self.queue = queue or []


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
