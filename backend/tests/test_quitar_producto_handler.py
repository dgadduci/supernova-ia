import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.handlers import (
    quitar_producto_handler as handler_module,
)
from backend.intents.handlers.quitar_producto_handler import execute_quitar_producto
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import (
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
)


def _ready_intent(
    pedido_producto_id: int | None = 1,
    cantidad: int | None = None,
    *,
    intent: str = "quitar_producto",
    handler: str = "quitar_producto",
    status: str = "ready",
) -> ProcessedIntent:
    literal_status = "ready" if status == "ready" else status
    return ProcessedIntent(
        intent=intent,
        source_text="x",
        status=literal_status,  # type: ignore[arg-type]
        recognizer="recognizer_quitar_producto",
        handler=handler,
        resolved_data={"pedido_producto_id": pedido_producto_id, "cantidad": cantidad},
        requirements=[
            RequirementState(name="pedido_producto_id", status="completed", value=pedido_producto_id),
            RequirementState(name="cantidad", status="completed" if cantidad is not None else "pending", value=cantidad),
        ],
        candidate_ids=[],
    )


class ExecuteQuitarProductoGuardsTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_intent_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(intent="agregar_producto", handler="agregar_producto")

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_ready_status_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(status="pending_resolution")

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_handler_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(handler="unknown")

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_integer_pedido_producto_id_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = ProcessedIntent(
            intent="quitar_producto",
            source_text="x",
            status="ready",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
            resolved_data={"pedido_producto_id": "not-int"},
        )

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_zero_cantidad_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=1, cantidad=0)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_pedido_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None
        intent = _ready_intent(pedido_producto_id=1)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()


class ExecuteQuitarProductoDecrementTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_partial_quantity_decrements_line(self, service_cls):
        current = MagicMock(id=10, cantidad=3)
        pp_assoc = current.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "Pizza Mozzarella"
        presentacion.codigo = "grande"
        presentacion.descripcion = "Pizza grande"

        service = MagicMock()
        service.get_for_pedido.return_value = current
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=10, cantidad=2)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["producto_nombre"], "Pizza Mozzarella")
        self.assertEqual(result.resolved_data["presentacion_codigo"], "grande")
        self.assertEqual(result.resolved_data["presentacion_descripcion"], "Pizza grande")
        self.assertEqual(result.resolved_data["cantidad_removida"], 2)
        self.assertEqual(result.resolved_data["cantidad_restante"], 1)
        self.assertEqual(result.resolved_data["linea_eliminada"], False)
        service.update.assert_called_once_with(10, cantidad=1, observaciones=None)


class ExecuteQuitarProductoDeleteTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_omit_quantity_deletes_line(self, service_cls):
        current = MagicMock(id=10, cantidad=3)
        pp_assoc = current.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "Pizza Mozzarella"
        presentacion.codigo = "grande"
        presentacion.descripcion = "Pizza grande"

        service = MagicMock()
        service.get_for_pedido.return_value = current
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=10, cantidad=None)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["linea_eliminada"], True)
        self.assertEqual(result.resolved_data["cantidad_removida"], 3)
        self.assertEqual(result.resolved_data["cantidad_restante"], 0)
        service.delete.assert_called_once_with(10)
        service.update.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_exact_quantity_deletes_line(self, service_cls):
        current = MagicMock(id=10, cantidad=2)
        pp_assoc = current.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "X"
        presentacion.codigo = "y"
        presentacion.descripcion = "Y"

        service = MagicMock()
        service.get_for_pedido.return_value = current
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=10, cantidad=2)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["linea_eliminada"], True)
        service.delete.assert_called_once_with(10)
        service.update.assert_not_called()


class ExecuteQuitarProductoExcessTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_excess_quantity_returns_rejected_without_mutation(self, service_cls):
        current = MagicMock(id=10, cantidad=2)
        pp_assoc = current.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "Pizza Mozzarella"
        presentacion.codigo = "docena"
        presentacion.descripcion = "Docena"

        service = MagicMock()
        service.get_for_pedido.return_value = current
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=10, cantidad=4)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data["cantidad_actual"], 2)
        self.assertEqual(result.resolved_data["producto_nombre"], "Pizza Mozzarella")
        self.assertEqual(result.resolved_data["presentacion_codigo"], "docena")
        service.update.assert_not_called()
        service.delete.assert_not_called()


class ExecuteQuitarProductoOwnershipTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_wrong_ownership_returns_rejected(self, service_cls):
        service = MagicMock()
        service.get_for_pedido.side_effect = PedidoProductoNotFound(99)
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=99, cantidad=1)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service.delete.assert_not_called()
        service.update.assert_not_called()


class ExecuteQuitarProductoBorradorGuardTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_borrador_only_guard_maps_to_rejected(self, service_cls):
        current = MagicMock(id=10, cantidad=2)
        pp_assoc = current.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "X"
        presentacion.codigo = "y"
        presentacion.descripcion = "Y"

        service = MagicMock()
        service.get_for_pedido.return_value = current
        service.delete.side_effect = PedidoProductoNotEditable(7, "confirmado")
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        intent = _ready_intent(pedido_producto_id=10)

        result = execute_quitar_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")


class ExecuteQuitarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(handler_module)
        with open(handler_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "from sqlalchemy import select",
            "joinedload",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "backend.old_project",
            "HTTPException",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            handler_module.__all__,
            ["execute_quitar_producto"],
        )


if __name__ == "__main__":
    unittest.main()