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

        def _detector_side_effect(message, catalog, **kwargs):
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
            def _side_effect(message, catalog, **kwargs):
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
    def test_paired_digit_quantities_extracted(self, pp_service_cls, catalog_cls):
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
            db,
            conversation_session,
            "cambiar dos napolitanas grandes por una pizza de mozzarella",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertEqual(result["cantidad_destino"], 1)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_paired_digit_quantities_extracted_when_both_digits(
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por 1 pizza de mozzarella",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertEqual(result["cantidad_destino"], 1)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_one_explicit_quantity_leaves_destination_none(
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
            db,
            conversation_session,
            "cambiar dos napolitanas grandes por mozzarella",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_zero_destination_quantity_signals_invalid(
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por 0 muzza",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_only_destination_quantity_routes_to_cantidad(
        self, pp_service_cls, catalog_cls
    ):
        """Contract case 3: legacy one-quantity semantics keep
        ``cantidad`` populated and ``cantidad_destino`` absent even when
        the only explicit quantity appears on the destination side.
        """
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
            db,
            conversation_session,
            "cambiar napolitanas por 2 mozzarellas",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_negative_destination_quantity_signals_invalid(
        self, pp_service_cls, catalog_cls
    ):
        """The probe must surface the explicit negative destination
        quantity even though the text normalizer strips the minus sign.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por -1 muzza",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_decimal_dot_destination_quantity_signals_invalid(
        self, pp_service_cls, catalog_cls
    ):
        """`1.5` MUST surface as an explicit invalid destination quantity
        even though the text normalizer strips the dot. Otherwise the
        legacy extractor would silently pick the ``1`` half of
        ``1 5`` and execute a wrong ``2 -> 1`` mutation.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por 1.5 mozzarellas",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_decimal_comma_destination_quantity_signals_invalid(
        self, pp_service_cls, catalog_cls
    ):
        """Spanish users commonly write ``1,5`` instead of ``1.5``. The
        recognizer MUST surface both as an explicit invalid destination
        quantity and never collapse to ``1`` or ``5``.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por 1,5 mozzarellas",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_decimal_with_colon_after_por_signals_invalid(
        self, pp_service_cls, catalog_cls
    ):
        """`por:` (colon-adjacent) MUST be recognised as a ``por``
        boundary in the raw text so the decimal destination token
        ``1.5`` is detected as explicit-invalid instead of being
        collapsed into ``1 5`` after normalization.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas por: 1.5 mozzarella",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_negative_with_comma_after_por_signals_invalid(
        self, pp_service_cls, catalog_cls
    ):
        """`por,` (comma-adjacent) MUST be recognised as a ``por``
        boundary so the negative destination quantity ``-1`` is
        surfaced as explicit-invalid.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas por, -1 mozzarella",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_por_token_inside_other_word_is_not_a_boundary(
        self, pp_service_cls, catalog_cls
    ):
        """`por` inside ``porcentaje`` MUST NOT be treated as a
        destination boundary; the message has no real destination side.
        """
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
            db,
            conversation_session,
            "cambiar 2 napolitanas grandes por porcentaje",
        )

        self.assertIsNone(result["cantidad_destino"])
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_no_por_boundary_leaves_destination_none(
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
            db,
            conversation_session,
            "cambiar 2 empanadas",
        )

        self.assertEqual(result["cantidad"], 2)
        self.assertIsNone(result["cantidad_destino"])

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


class RecognizeModificarProductoHybridProjectionTest(unittest.TestCase):
    """The hybrid authoritative recognizer emits recognized presentation
    IDs but never the order-line primary key. The recognizer must
    recover ``pedido_producto_id`` exclusively from the source catalog
    it already built for the active draft Pedido, without widening
    candidates or trusting values the recognizer might have carried
    in.
    """

    @staticmethod
    def _make_pedido_producto(
        *, line_id: int, presentation_id: int, nombre: str = "Pizza"
    ):
        pp = MagicMock(id=line_id)
        pp.producto_presentacion.producto.nombre = nombre
        pp.producto_presentacion.presentacion.codigo = "chica"
        pp.producto_presentacion.id_producto = 1
        pp.producto_presentacion.id_presentacion = 1
        pp.producto_presentacion.producto.id_categoria_producto = 1
        pp.producto_presentacion.producto.activo = True
        pp.producto_presentacion.producto.disponible = True
        pp.producto_presentacion.presentacion.activo = True
        pp.producto_presentacion.activo = True
        pp.id_producto_presentacion = presentation_id
        pp.cantidad = 1
        return pp

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_unique_source_restores_line_id_from_catalog(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Napolitana"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
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
                        "producto_presentacion_id": 101,
                        "producto_nombre": "Pizza Napolitana",
                        "cantidad": 2,
                        "texto_origen": message,
                    }
                ],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar 2 napolitanas por 2 muzza"
            )

        self.assertEqual(result["source_candidate_ids"], [41])
        self.assertEqual(result["source_pp_id"], 41)
        self.assertEqual(result["destination_candidate_ids"], [])
        self.assertIsNone(result["destination_pp_id"])
        self.assertEqual(result["cantidad"], 2)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_ambiguous_source_restricts_to_own_lines(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp_a = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Mozzarella"
        )
        pp_b = self._make_pedido_producto(
            line_id=42, presentation_id=102, nombre="Pizza Napolitana"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp_a, pp_b]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
            if not catalog:
                return {
                    "encontrados": [],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }
            return {
                "encontrados": [],
                "encontrados_posibles": [
                    {
                        "texto_origen": message,
                        "productos": [
                            {
                                "producto_presentacion_id": 101,
                                "producto_nombre": "Pizza Mozzarella",
                                "texto_origen": message,
                            },
                            {
                                "producto_presentacion_id": 102,
                                "producto_nombre": "Pizza Napolitana",
                                "texto_origen": message,
                            },
                        ],
                    }
                ],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar pizza por napolitana"
            )

        self.assertEqual(set(result["source_candidate_ids"]), {41, 42})
        self.assertIsNone(result["source_pp_id"])
        self.assertEqual(result["destination_candidate_ids"], [])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_unmapped_source_does_not_contribute(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Mozzarella"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
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
                        "producto_presentacion_id": 999,
                        "producto_nombre": "Pizza Foranea",
                        "cantidad": 1,
                        "texto_origen": message,
                    }
                ],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar la foranea por muzza"
            )

        self.assertEqual(result["source_candidate_ids"], [])
        self.assertEqual(result["destination_candidate_ids"], [])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_carries_wrong_line_id_is_overwritten(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Napolitana"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
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
                        "producto_presentacion_id": 101,
                        "pedido_producto_id": 999,
                        "producto_nombre": "Pizza Napolitana",
                        "cantidad": 2,
                        "texto_origen": message,
                    }
                ],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar 2 napolitanas por 2 muzza"
            )

        self.assertEqual(result["source_candidate_ids"], [41])
        self.assertEqual(result["source_pp_id"], 41)
        self.assertNotIn(999, result["source_candidate_ids"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_category_source_group_preserves_shape(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Mozzarella"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
            if not catalog:
                return {
                    "encontrados": [],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }
            return {
                "encontrados": [],
                "encontrados_posibles": [
                    {
                        "kind": "category",
                        "categoria_nombre": "Pizzas",
                        "texto_origen": message,
                    }
                ],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar la pizza por napolitana"
            )

        self.assertEqual(result["source_candidate_ids"], [])
        self.assertEqual(result["destination_candidate_ids"], [])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_malformed_source_does_not_contribute(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Napolitana"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
        pp_service_cls.return_value = pp_service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        def _detector_side_effect(message, catalog, **kwargs):
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
                        "producto_presentacion_id": "no-es-int",
                        "producto_nombre": "Pizza Rara",
                        "cantidad": 1,
                        "texto_origen": message,
                    },
                    {
                        "producto_nombre": "Sin presentacion",
                        "cantidad": 1,
                        "texto_origen": message,
                    },
                ],
                "encontrados_posibles": [
                    {
                        "texto_origen": message,
                        "productos": [
                            {
                                "producto_presentacion_id": True,
                                "producto_nombre": "Bool id",
                                "texto_origen": message,
                            }
                        ],
                    }
                ],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar algo por otra cosa"
            )

        self.assertEqual(result["source_candidate_ids"], [])
        self.assertEqual(result["destination_candidate_ids"], [])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_hybrid_source_destination_separation_under_hybrid(
        self, pp_service_cls, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = self._make_pedido_producto(
            line_id=41, presentation_id=101, nombre="Pizza Napolitana"
        )
        pp_service = MagicMock()
        pp_service.list_by_pedido.return_value = [pp]
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

        def _detector_side_effect(message, catalog, **kwargs):
            catalog_ids = {
                int(entry["producto_presentacion_id"])
                for entry in catalog
                if entry.get("producto_presentacion_id") is not None
            }
            if 200 in catalog_ids:
                return {
                    "encontrados": [
                        {
                            "producto_presentacion_id": 200,
                            "producto_nombre": "Pizza Mozzarella",
                            "cantidad": 1,
                            "texto_origen": message,
                        }
                    ],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }
            if 101 in catalog_ids:
                return {
                    "encontrados": [
                        {
                            "producto_presentacion_id": 101,
                            "producto_nombre": "Pizza Napolitana",
                            "cantidad": 2,
                            "texto_origen": message,
                        }
                    ],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(
            recognizer_module,
            "detectar_productos",
            side_effect=_detector_side_effect,
        ):
            result = recognize_modificar_producto(
                db, conversation_session, "cambiar 2 napolitanas por muzza"
            )

        self.assertEqual(result["source_candidate_ids"], [41])
        self.assertEqual(result["source_pp_id"], 41)
        self.assertEqual(result["destination_candidate_ids"], [200])
        self.assertEqual(result["destination_pp_id"], 200)
        self.assertEqual(
            set(result["source_candidate_ids"]).intersection(
                result["destination_candidate_ids"]
            ),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
