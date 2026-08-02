import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers import (
    quitar_producto_recognizer as recognizer_module,
)
from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.models.session import Session as ConversationSession


class RecognizeQuitarProductoCatalogTest(unittest.TestCase):
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "detectar_productos")
    def test_catalog_limited_to_pedido_producto_lines(
        self, detectar, service_cls
    ):
        pp1 = MagicMock(id=1, id_producto_presentacion=10, cantidad=2)
        pp1.producto_presentacion.presentacion.codigo = "grande"
        pp1.producto_presentacion.presentacion.descripcion = "Grande"
        pp1.producto_presentacion.producto.nombre = "Pizza"
        pp1.producto_presentacion.producto.activo = True
        pp1.producto_presentacion.producto.disponible = True
        pp1.producto_presentacion.activo = True

        pp2 = MagicMock(id=2, id_producto_presentacion=20, cantidad=1)
        pp2.producto_presentacion.presentacion.codigo = "docena"
        pp2.producto_presentacion.presentacion.descripcion = "Docena"
        pp2.producto_presentacion.producto.nombre = "Empanada"
        pp2.producto_presentacion.producto.activo = True
        pp2.producto_presentacion.producto.disponible = True
        pp2.producto_presentacion.activo = True

        service = MagicMock()
        service.list_by_pedido.return_value = [pp1, pp2]
        service_cls.return_value = service
        detectar.return_value = {
            "encontrados": [
                {
                    "producto_presentacion_id": 10,
                    "cantidad": 2,
                    "producto_nombre": "Pizza",
                    "presentacion_codigo": "grande",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = recognize_quitar_producto(db, session, "pizza grande")

        service.list_by_pedido.assert_called_once_with(7)
        detectar.assert_called_once()
        catalog_arg = detectar.call_args.args[1]
        self.assertEqual(len(catalog_arg), 2)
        self.assertEqual(catalog_arg[0]["pedido_producto_id"], 1)
        self.assertEqual(catalog_arg[0]["producto_presentacion_id"], 10)
        self.assertEqual(catalog_arg[0]["producto_nombre"], "Pizza")
        self.assertEqual(catalog_arg[0]["presentacion_codigo"], "grande")
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["pedido_producto_id"], 1)

    @patch.object(recognizer_module, "PedidoProductoService")
    def test_empty_pedido_yields_no_candidates(self, service_cls):
        service = MagicMock()
        service.list_by_pedido.return_value = []
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 8

        result = recognize_quitar_producto(db, session, "pizza")

        self.assertEqual(result["encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(result["cantidad"], None)

    @patch.object(recognizer_module, "PedidoProductoService")
    def test_missing_pedido_yields_no_candidates(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        result = recognize_quitar_producto(db, session, "pizza")

        service_cls.assert_not_called()
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(result["cantidad"], None)


class RecognizeQuitarProductoQuantityTest(unittest.TestCase):
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "detectar_productos")
    def test_explicit_quantity_is_extracted(self, detectar, service_cls):
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service_cls.return_value = service
        detectar.return_value = {
            "encontrados": [
                {
                    "producto_presentacion_id": 1,
                    "cantidad": 1,
                    "producto_nombre": "X",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = recognize_quitar_producto(db, session, "quitá 2 empanadas")

        self.assertEqual(result["cantidad"], 2)
        self.assertEqual(result["encontrados"][0]["cantidad"], 2)

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "detectar_productos")
    def test_missing_quantity_yields_none(self, detectar, service_cls):
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service_cls.return_value = service
        detectar.return_value = {
            "encontrados": [
                {
                    "producto_presentacion_id": 1,
                    "cantidad": 1,
                    "producto_nombre": "X",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = recognize_quitar_producto(db, session, "sacala")

        self.assertIsNone(result["cantidad"])


class RecognizeQuitarProductoInactiveProductTest(unittest.TestCase):
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "detectar_productos")
    def test_inactive_catalog_product_in_pedido_remains_reachable(
        self, detectar, service_cls
    ):
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service_cls.return_value = service
        detectar.return_value = {
            "encontrados": [
                {
                    "producto_presentacion_id": 1,
                    "cantidad": 1,
                    "producto_nombre": "X",
                    "presentacion_codigo": "x",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = recognize_quitar_producto(db, session, "x")

        self.assertEqual(len(result["encontrados"]), 1)


class RecognizeQuitarProductoNoMutationTest(unittest.TestCase):
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "detectar_productos")
    def test_recognizer_does_not_mutate_session_or_pedido(
        self, detectar, service_cls
    ):
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service_cls.return_value = service
        detectar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "x"}],
        }

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        recognize_quitar_producto(db, session, "xyz")

        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()


class RecognizeQuitarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_repository_directly(self):
        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("PedidoProductoRepository", source)
        self.assertNotIn("from sqlalchemy import select", source)
        self.assertNotIn("joinedload", source)
        self.assertNotIn("from backend.routers", source)
        self.assertNotIn("from backend.llm", source)
        self.assertNotIn("from backend.repositories", source)
        self.assertNotIn("backend.old_project", source)

    def test_module_uses_service_layer(self):
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("PedidoProductoService", source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            recognizer_module.__all__, ["recognize_quitar_producto"]
        )


if __name__ == "__main__":
    unittest.main()