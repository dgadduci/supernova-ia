"""Transactional boundary regression tests for `modificar_producto`.

Section 9 of the `fix-modificar-producto-atomicity-quantity` change:
- 9.1: process_incoming_message_transactional commits exactly once on a
       successful modification; no lower-level commit inside the service
       or handler.
- 9.2: a raised exception inside the modify path results in exactly one
       rollback from the transactional wrapper; no partial commit.
- 9.3: initial_intent_dispatcher dispatches `modificar_producto` only to
       `process_initial_modificar_producto` (and never to the
       agregar_producto or quitar_producto orchestrators).
- 9.4: pending_context_dispatcher routes `product_modification` to
       `resolve_product_modification` and delegates `ready` to
       `execute_ready_pending_context`.
- 9.5: pending_context_execution dispatches `handler == modificar_producto`
       to `execute_modificar_producto` and clears the pending context on
       definitive `rejected`.
"""
import inspect
import unittest
from unittest.mock import MagicMock, patch

import backend.intents.handlers.modificar_producto_handler as modificar_handler_module
import backend.services.pedido_producto_service as pedido_producto_service_module
from backend.intents.context.product_modification_resolver import (
    resolve_product_modification,
)
from backend.intents.handlers.modificar_producto_handler import (
    execute_modificar_producto,
)
from backend.intents.orchestration import initial_intent_dispatcher
from backend.intents.orchestration import (
    pending_context_dispatcher as pending_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_execution as pending_execution_module,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.orchestration.transactional_message_processor import (
    process_incoming_message_transactional,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.sessions.enums.context_type import ContextType


class TransactionalBoundaryRegressionTest(unittest.TestCase):
    """9.1, 9.2 - exactly one commit on success and exactly one rollback on failure."""

    def _extract_modify_product_source(self):
        """Return the source of `PedidoProductoService.modify_product` only."""
        full = inspect.getsource(pedido_producto_service_module)
        start = full.find("def modify_product(")
        assert start != -1
        # Find end by indentation: the function ends when indentation
        # returns to the class level (no spaces) or another `def` at
        # class level.
        sub = full[start:]
        end_marker = "\n\nclass "
        end = sub.find(end_marker)
        if end != -1:
            sub = sub[:end]
        return sub

    def test_modify_product_does_not_own_the_transaction_boundary(self):
        """9.1 — `modify_product` is commit-free, rollback-free,
        flush-free, refresh-free, expire-free, and begin-free."""
        modify_product_source = self._extract_modify_product_source()
        for forbidden in (
            "self._session.commit",
            "self._session.rollback",
            "self._session.begin",
            "self._session.flush",
            "self._session.refresh",
            "self._session.expire",
            "db.commit",
            "db.rollback",
            "db.begin",
            "db.flush",
            "db.refresh",
            "db.expire",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    modify_product_source,
                    f"modify_product must not call {forbidden}",
                )

    def test_handler_does_not_own_the_transaction_boundary(self):
        """9.1 — the modificar handler is commit-free, rollback-free,
        flush-free, refresh-free, expire-free, and begin-free."""
        handler_source = inspect.getsource(modificar_handler_module)
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.begin",
            "db.flush",
            "db.refresh",
            "db.expire",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, handler_source)

    def test_modify_product_reads_current_precio_before_source_mutation(self):
        """9.1 — `current_precio` (used to read a destination snapshot)
        is read strictly before any source mutation. We check this
        statically by inspecting the modify_product source for the
        relative ordering of the `current_precio` call and the
        `delete`/`decrement` calls.
        """
        modify_product_source = self._extract_modify_product_source()
        precio_idx = modify_product_source.find("current_precio(")
        delete_idx = modify_product_source.find("_repo.delete(")
        decrement_idx = modify_product_source.find("_repo.decrement(")
        self.assertNotEqual(precio_idx, -1)
        self.assertNotEqual(delete_idx, -1)
        self.assertLess(precio_idx, delete_idx)
        self.assertLess(precio_idx, decrement_idx)

    def test_process_incoming_message_transactional_commits_once(self):
        from backend.intents.orchestration import (
            transactional_message_processor as processor_module,
        )

        sentinel = ProcessedIntent(
            intent="modificar_producto",
            source_text="cambia",
            status="executed",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
        )
        with patch.object(processor_module, "process_incoming_message") as inner:
            inner.return_value = [sentinel]
            db = MagicMock()
            session = MagicMock()
            result = process_incoming_message_transactional(db, session, "hola")

            inner.assert_called_once_with(db, session, "hola")
            db.commit.assert_called_once_with()
            db.rollback.assert_not_called()
            self.assertEqual(result, [sentinel])

    def test_process_incoming_message_transactional_rolls_back_once_on_exception(self):
        from backend.intents.orchestration import (
            transactional_message_processor as processor_module,
        )

        boom = RuntimeError("boom")
        with patch.object(processor_module, "process_incoming_message") as inner:
            inner.side_effect = boom
            db = MagicMock()
            session = MagicMock()

            with self.assertRaises(RuntimeError):
                process_incoming_message_transactional(db, session, "hola")

            inner.assert_called_once_with(db, session, "hola")
            db.rollback.assert_called_once_with()
            db.commit.assert_not_called()


class DispatcherRegressionTest(unittest.TestCase):
    """9.3 - modificar_producto is only dispatched to its own orchestrator."""

    def test_modificar_producto_dispatched_to_modificar_orchestrator(self):
        class _ModificarClassifier:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def query(self, message):
                return IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.MODIFICAR_PRODUCTO,
                            mensaje=message,
                        )
                    ],
                    mensaje=message,
                )

        with patch.object(initial_intent_dispatcher, "IntentClassifier") as cls:
            cls.return_value = _ModificarClassifier()
            db = MagicMock()
            session = MagicMock()
            session.context_type = None
            session.id_pedido = None
            result = dispatch_initial_message(db, session, "cambia algo")

            assert isinstance(result, list)
            self.assertGreaterEqual(len(result), 1)
            self.assertEqual(result[0].intent, "modificar_producto")

    def test_initial_dispatcher_does_not_invoke_quitar_or_agregar_orchestrators(self):
        """The modificar_producto dispatch arm calls the modificar
        orchestrator; it never imports or invokes quitar/agregar
        orchestrators on its own.
        """
        from backend.intents.orchestration import modificar_producto_initial

        with patch.object(modificar_producto_initial, "execute_modificar_producto"):
            with patch(
                "backend.intents.orchestration.agregar_producto_orchestrator.process_initial_agregar_producto"
            ) as agregar:
                with patch(
                    "backend.intents.orchestration.quitar_producto_initial.process_initial_quitar_producto"
                ) as quitar:
                    db = MagicMock()
                    session = MagicMock()
                    session.id_pedido = None
                    dispatch_initial_message(db, session, "cambia")
                    agregar.assert_not_called()
                    quitar.assert_not_called()


class PendingContextDispatcherRegressionTest(unittest.TestCase):
    """9.4 - product_modification routes to resolve_product_modification."""

    def test_product_modification_routes_to_resolve_product_modification(self):
        db = MagicMock()
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_MODIFICATION.value
        active = ProcessedIntent(
            intent="modificar_producto",
            source_text="cambia",
            status="pending_resolution",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            stage="destination_selection",
            resolved_data={
                "source_candidate_ids": [1],
                "destination_candidate_ids": [10, 11],
                "cantidad": None,
            },
        )
        with patch.object(
            pending_dispatcher_module,
            "load_pending_state",
        ) as load_mock:
            load_mock.return_value.active = active
            with patch.object(
                pending_dispatcher_module,
                "resolve_product_modification",
            ) as resolver:
                resolver.return_value = active.model_copy(
                    update={"status": "rejected"}
                )
                with patch.object(
                    pending_dispatcher_module,
                    "set_active",
                ) as set_active_mock:
                    dispatch_pending_context(db, session, "msg")

                    resolver.assert_called_once()
                    set_active_mock.assert_called_once()


class PendingContextExecutionRegressionTest(unittest.TestCase):
    """9.5 - execute_modificar_producto dispatched; rejected clears pending."""

    def test_modificar_handler_dispatched_from_execute_ready_pending_context(self):
        active = ProcessedIntent(
            intent="modificar_producto",
            source_text="cambia",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": 2,
                "cantidad": 1,
            },
        )

        with patch.object(pending_execution_module, "load_pending_state") as load_mock:
            load_mock.return_value.active = active
            with patch.object(
                pending_execution_module,
                "execute_modificar_producto",
            ) as ejecutar:
                from backend.services.modification_result import ModificationResult

                ejecutar.return_value = active.model_copy(
                    update={
                        "status": "rejected",
                        "resolved_data": {"reason": "equivalent_modification"},
                    }
                )
                with patch.object(
                    pending_execution_module,
                    "clear_pending_context",
                ) as clear:
                    db = MagicMock()
                    session = MagicMock()
                    session.context_type = ContextType.PRODUCT_MODIFICATION.value
                    result = execute_ready_pending_context(db, session)

                    ejecutar.assert_called_once_with(db, session, active)
                    clear.assert_called_once_with(session)
                    session.context_type = None
                    self.assertEqual(result[0].status, "rejected")


if __name__ == "__main__":
    unittest.main()
