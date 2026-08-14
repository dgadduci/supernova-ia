import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.handlers import (
    modificar_producto_handler as handler_module,
)
from backend.intents.handlers.modificar_producto_handler import (
    execute_modificar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession
from backend.services.modification_result import ModificationResult


def _ready_intent(
    *,
    pedido_producto_origen_id: int | None = 1,
    producto_presentacion_destino_id: int | None = 2,
    cantidad: int | None = None,
    intent: str = "modificar_producto",
    handler: str = "modificar_producto",
    status: str = "ready",
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent,
        source_text="x",
        status=status,  # type: ignore[arg-type]
        recognizer="modificar_producto_recognizer",
        handler=handler,
        resolved_data={
            "pedido_producto_origen_id": pedido_producto_origen_id,
            "producto_presentacion_destino_id": producto_presentacion_destino_id,
            "cantidad": cantidad,
        },
        requirements=[
            RequirementState(
                name="pedido_producto_origen_id",
                status="completed" if pedido_producto_origen_id is not None else "pending",
                value=pedido_producto_origen_id,
            ),
            RequirementState(
                name="producto_presentacion_destino_id",
                status="completed" if producto_presentacion_destino_id is not None else "pending",
                value=producto_presentacion_destino_id,
            ),
            RequirementState(
                name="cantidad",
                status="completed" if cantidad is not None else "pending",
                value=cantidad,
            ),
        ],
        candidate_ids=[],
    )


class ExecuteModificarProductoGuardsTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_intent_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(intent="quitar_producto", handler="quitar_producto")

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_ready_status_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(status="pending_resolution")

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_handler_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(handler="unknown")

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_integer_source_id_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": "not-int",
                "producto_presentacion_destino_id": 2,
            },
        )

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_integer_destination_id_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": "not-int",
            },
        )

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_zero_cantidad_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(cantidad=0)

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_zero_cantidad_destino_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": 2,
                "cantidad": 2,
                "cantidad_destino": 0,
            },
        )

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_integer_cantidad_destino_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": 2,
                "cantidad": 2,
                "cantidad_destino": "no-int",
            },
        )

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_distinct_cantidades_passed_to_service(self, service_cls):
        service = MagicMock()
        service.modify_product.return_value = ModificationResult(
            status="executed",
            producto_origen_nombre="Pizza Napolitana",
            presentacion_origen="grande",
            producto_destino_nombre="Pizza Mozzarella",
            presentacion_destino="grande",
            cantidad_modificada=2,
            cantidad_origen_restante=3,
            cantidad_destino_final=1,
            origen_eliminado=False,
            destino_creado=True,
            cantidad_destino_modificada=1,
        )
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": 2,
                "cantidad": 2,
                "cantidad_destino": 1,
            },
        )

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["cantidad_destino_modificada"], 1)
        service.modify_product.assert_called_once_with(7, 1, 2, 2, 1)

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_pedido_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None
        intent = _ready_intent()

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()


class ExecuteModificarProductoExecutionTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_successful_execution_returns_executed_with_enrichment(self, service_cls):
        service = MagicMock()
        service.modify_product.return_value = ModificationResult(
            status="executed",
            producto_origen_nombre="Pizza Mozzarella",
            presentacion_origen="chica",
            producto_destino_nombre="Pizza Mozzarella",
            presentacion_destino="grande",
            cantidad_modificada=2,
            cantidad_origen_restante=0,
            cantidad_destino_final=2,
            origen_eliminado=True,
            destino_creado=True,
            cantidad_destino_modificada=2,
        )
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(cantidad=2)

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(
            result.resolved_data["producto_origen_nombre"], "Pizza Mozzarella"
        )
        self.assertEqual(result.resolved_data["presentacion_origen"], "chica")
        self.assertEqual(
            result.resolved_data["producto_destino_nombre"], "Pizza Mozzarella"
        )
        self.assertEqual(result.resolved_data["presentacion_destino"], "grande")
        self.assertEqual(result.resolved_data["cantidad_modificada"], 2)
        self.assertEqual(result.resolved_data["cantidad_origen_restante"], 0)
        self.assertEqual(result.resolved_data["cantidad_destino_final"], 2)
        self.assertEqual(result.resolved_data["cantidad_destino_modificada"], 2)
        self.assertTrue(result.resolved_data["origen_eliminado"])
        self.assertTrue(result.resolved_data["destino_creado"])
        service.modify_product.assert_called_once_with(
            7, 1, 2, 2, None
        )

    @patch.object(handler_module, "PedidoProductoService")
    def test_service_rejected_quantity_exceeds(self, service_cls):
        service = MagicMock()
        service.modify_product.return_value = ModificationResult(
            status="rejected",
            reason="quantity_exceeds_source",
            cantidad_actual=2,
            producto_origen_nombre="Empanadas de carne",
            presentacion_origen="docena",
        )
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(cantidad=5)

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data["reason"], "quantity_exceeds_source")
        self.assertEqual(result.resolved_data["cantidad_actual"], 2)

    @patch.object(handler_module, "PedidoProductoService")
    def test_service_rejected_equivalent_modification(self, service_cls):
        service = MagicMock()
        service.modify_product.return_value = ModificationResult(
            status="rejected", reason="equivalent_modification"
        )
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent()

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data["reason"], "equivalent_modification"
        )

    @patch.object(handler_module, "PedidoProductoService")
    def test_unexpected_exception_propagates(self, service_cls):
        service = MagicMock()
        service.modify_product.side_effect = RuntimeError("boom")
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent()

        with self.assertRaises(RuntimeError):
            execute_modificar_producto(db, session, intent)

    @patch.object(handler_module, "PedidoProductoService")
    def test_modification_failed_sentinel_translates_to_failed(self, service_cls):
        from backend.services.exceptions import ModificationFailed

        service = MagicMock()
        service.modify_product.side_effect = ModificationFailed("oops")
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent()

        result = execute_modificar_producto(db, session, intent)

        self.assertEqual(result.status, "failed")


class ExecuteModificarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback_or_flush(self):
        importlib.reload(handler_module)
        with open(handler_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "from sqlalchemy import select",
            "joinedload",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "from backend.intents.responses",
            "from backend.old_project",
            "except BaseException",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_does_not_catch_broad_exception(self):
        importlib.reload(handler_module)
        with open(handler_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("except Exception:", source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            handler_module.__all__,
            ["execute_modificar_producto"],
        )


if __name__ == "__main__":
    unittest.main()
