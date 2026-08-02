import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers import (
    modificar_producto_recognizer as recognizer_module,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    recognize_modificar_producto,
)
from backend.models.session import Session as ConversationSession


class RecognizeModificarProductoSourceTest(unittest.TestCase):
    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_source_limited_to_draft_pedido(self, pp_service_cls, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_a = MagicMock(id=11)
        pp_a.producto_presentacion.producto.nombre = "Pizza Mozzarella"
        pp_a.producto_presentacion.presentacion.codigo = "chica"
        pp_a.producto_presentacion.id_producto = 1
        pp_a.producto_presentacion.id_presentacion = 1
        pp_a.producto_presentacion.producto.id_categoria_producto = 1
        pp_a.producto_presentacion.producto.activo = True
        pp_a.producto_presentacion.producto.disponible = True
        pp_a.producto_presentacion.presentacion.activo = True
        pp_a.producto_presentacion.activo = True
        pp_a.id_producto_presentacion = 100
        pp_a.cantidad = 2

        pp_b = MagicMock(id=12)
        pp_b.producto_presentacion.producto.nombre = "Pizza Napolitana"
        pp_b.producto_presentacion.presentacion.codigo = "chica"
        pp_b.producto_presentacion.id_producto = 2
        pp_b.producto_presentacion.id_presentacion = 1
        pp_b.producto_presentacion.producto.id_categoria_producto = 1
        pp_b.producto_presentacion.producto.activo = True
        pp_b.producto_presentacion.producto.disponible = True
        pp_b.producto_presentacion.presentacion.activo = True
        pp_b.producto_presentacion.activo = True
        pp_b.id_producto_presentacion = 101
        pp_b.cantidad = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp_a, pp_b]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog):
            if not catalog:
                return {
                    "encontrados": [],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }
            return {
                "encontrados": [
                    {
                        "producto_presentacion_id": 100,
                        "pedido_producto_id": 11,
                    },
                    {
                        "producto_presentacion_id": 101,
                        "pedido_producto_id": 12,
                    },
                ],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module, "detectar_productos", side_effect=_detector_side_effect
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "pizza chica"
            )

        self.assertEqual(set(result["source_candidate_ids"]), {11, 12})
        self.assertEqual(result["destination_candidate_ids"], [])
        self.assertIsNone(result["source_pp_id"])
        self.assertIsNone(result["destination_pp_id"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_source_empty_when_no_lines(self, pp_service_cls, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = []
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        result = recognize_modificar_producto(
            db, conversation_session, "cambiá algo"
        )

        self.assertEqual(result["source_candidate_ids"], [])
        self.assertEqual(result["destination_candidate_ids"], [])


class RecognizeModificarProductoDestinationTest(unittest.TestCase):
    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_destination_limited_to_active_catalog(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = None
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = [
            {
                "producto_presentacion_id": 200,
                "producto_activo": True,
                "presentacion_activo": True,
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 201,
                "producto_activo": True,
                "presentacion_activo": True,
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 999,
                "producto_activo": False,
                "presentacion_activo": True,
                "activo": True,
                "disponible": True,
            },
        ]
        catalog_cls.return_value = catalog_service

        with patch.object(
            recognizer_module, "detectar_productos"
        ) as detector:
            def _side_effect(message, catalog):
                pp_ids_in_catalog = {
                    entry["producto_presentacion_id"] for entry in catalog
                }
                encontrados = [
                    {"producto_presentacion_id": pid}
                    for pid in (200, 201, 999)
                    if pid in pp_ids_in_catalog
                ]
                return {
                    "encontrados": encontrados,
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }

            detector.side_effect = _side_effect
            result = recognize_modificar_producto(
                db, conversation_session, "pizza"
            )

        self.assertEqual(set(result["destination_candidate_ids"]), {200, 201})
        self.assertNotIn(999, result["destination_candidate_ids"])


class RecognizeModificarProductoQuantityTest(unittest.TestCase):
    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_explicit_positive_quantity_extracted(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = []
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        result = recognize_modificar_producto(
            db, conversation_session, "cambiá 2 empanadas por 2 de jamón"
        )

        self.assertEqual(result["cantidad"], 2)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_omitted_quantity_returns_none(self, pp_service_cls, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = []
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        result = recognize_modificar_producto(
            db, conversation_session, "cambiá empanadas por jamón"
        )

        self.assertIsNone(result["cantidad"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_zero_quantity_returns_none(self, pp_service_cls, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = []
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        result = recognize_modificar_producto(
            db, conversation_session, "cambiá 0 empanadas por jamón"
        )

        self.assertIsNone(result["cantidad"])


class RecognizeModificarProductoDistinctDomainsTest(unittest.TestCase):
    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_domains_never_overlap(self, pp_service_cls, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = []
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = [
            {
                "producto_presentacion_id": 200,
                "producto_activo": True,
                "presentacion_activo": True,
                "activo": True,
                "disponible": True,
            }
        ]
        catalog_cls.return_value = catalog_service

        with patch.object(
            recognizer_module, "detectar_productos"
        ) as detector:
            detector.return_value = {
                "encontrados": [{"producto_presentacion_id": 200}],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }
            result = recognize_modificar_producto(
                db, conversation_session, "algo"
            )

        self.assertEqual(set(result["source_candidate_ids"]), set())
        self.assertEqual(set(result["destination_candidate_ids"]), {200})
        self.assertEqual(
            set(result["source_candidate_ids"]).intersection(
                result["destination_candidate_ids"]
            ),
            set(),
        )


class RecognizeModificarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback(self):
        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.add",
            "db.delete",
            "from backend.llm",
            "from backend.routers",
            "from fastapi",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            recognizer_module.__all__,
            ["recognize_modificar_producto"],
        )


if __name__ == "__main__":
    unittest.main()
