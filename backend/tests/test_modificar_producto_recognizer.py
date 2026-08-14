import importlib
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers import (
    modificar_producto_recognizer as recognizer_module,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    _build_order_line_catalog,
    recognize_modificar_producto,
)
from backend.models.session import Session as ConversationSession
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer


@contextmanager
def _patched_real_fuzzy():
    """Replace the modification recognizer's module-level
    ``_product_recognizer`` with a real ``FuzzyProductRecognizer`` for
    the duration of the test.

    The wrapper ``recognizer_module.detectar_productos`` continues to
    be the production callable; only the underlying recognizer object
    is swapped for the deterministic, in-process fuzzy instance. The
    real fuzzy executes against the catalog with eager-loaded
    ``categoria_nombre`` produced by ``_build_order_line_catalog``,
    so the test exercises the real production code path end-to-end.
    """
    original = recognizer_module._product_recognizer
    recognizer_module._product_recognizer = FuzzyProductRecognizer()
    try:
        yield
    finally:
        recognizer_module._product_recognizer = original


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
    def test_only_destination_quantity_routes_to_cantidad_destino(
        self, pp_service_cls, catalog_cls
    ):
        """Contract: when the only explicit quantity appears on the
        destination side, ``cantidad`` MUST be ``None`` and
        ``cantidad_destino`` MUST carry that value so the handler re-
        reads the full source line and applies the destination amount.
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

        self.assertIsNone(result["cantidad"])
        self.assertEqual(result["cantidad_destino"], 2)
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_only_destination_quantity_word_form_routes_to_cantidad_destino(
        self, pp_service_cls, catalog_cls
    ):
        """Word-form destination quantity (``dos``) must behave the same
        as the digit form: ``cantidad`` stays ``None`` and
        ``cantidad_destino`` carries the value.
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
            "cambiar la napolitana grande por dos mozzarellas grandes",
        )

        self.assertIsNone(result["cantidad"])
        self.assertEqual(result["cantidad_destino"], 2)
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_paired_destination_quantity_preserves_explicit_source(
        self, pp_service_cls, catalog_cls
    ):
        """Regression: source explicit + destination explicit must keep
        the existing ``cantidad=source_value, cantidad_destino=dest_value``
        contract; the destination-only branch change must not bleed into
        the paired branch.
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
            "cambiar 1 napolitana por 2 mozzarellas",
        )

        self.assertEqual(result["cantidad"], 1)
        self.assertEqual(result["cantidad_destino"], 2)
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_only_source_quantity_keeps_cantidad_only(
        self, pp_service_cls, catalog_cls
    ):
        """Regression: only the source side has an explicit quantity;
        the recognizer must keep the legacy
        ``cantidad=source_value, cantidad_destino=None`` contract so the
        destination mirrors the source amount.
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
            "cambiar 3 napolitanas por mozzarella",
        )

        self.assertEqual(result["cantidad"], 3)
        self.assertIsNone(result["cantidad_destino"])
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_omitted_both_sides_returns_none_none(
        self, pp_service_cls, catalog_cls
    ):
        """Regression: no explicit quantity on either side. Both fields
        are ``None``; the handler re-reads the full source quantity.
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
            "cambiar la napolitana por la mozzarella",
        )

        self.assertIsNone(result["cantidad"])
        self.assertIsNone(result["cantidad_destino"])
        self.assertFalse(result["cantidad_destino_invalid"])

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_destination_only_with_source_in_catalog_keeps_none(
        self, pp_service_cls, catalog_cls
    ):
        """When the destination-only message also has a unique source
        line available, the recognizer must still emit
        ``cantidad=None``/``cantidad_destino=M`` so the handler does
        the full source removal.
        """
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        pp = MagicMock(id=41)
        pp.producto_presentacion.producto.nombre = "Pizza Napolitana"
        pp.producto_presentacion.presentacion.codigo = "grande"
        pp.producto_presentacion.id_producto = 1
        pp.producto_presentacion.id_presentacion = 1
        pp.producto_presentacion.producto.id_categoria_producto = 1
        pp.producto_presentacion.producto.activo = True
        pp.producto_presentacion.producto.disponible = True
        pp.producto_presentacion.presentacion.activo = True
        pp.producto_presentacion.activo = True
        pp.id_producto_presentacion = 101
        pp.cantidad = 1

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
                        "pedido_producto_id": 41,
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
                db,
                conversation_session,
                "cambia la napolitana grande por dos mozzarellas grandes",
            )

        self.assertIsNone(result["cantidad"])
        self.assertEqual(result["cantidad_destino"], 2)
        self.assertFalse(result["cantidad_destino_invalid"])
        self.assertEqual(result["source_pp_id"], 41)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_invalid_destination_quantity_overrides_destination_only(
        self, pp_service_cls, catalog_cls
    ):
        """Even with no explicit source quantity, an invalid destination
        quantity (``0``, ``-1``, ``1.5``, ``1,5``) must still surface
        ``cantidad_destino_invalid=True`` and not be routed to
        ``cantidad_destino``.
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
            "cambiar napolitanas por 0 mozzarellas",
        )

        self.assertIsNone(result["cantidad"])
        self.assertIsNone(result["cantidad_destino"])
        self.assertTrue(result["cantidad_destino_invalid"])

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
        *,
        line_id: int,
        presentation_id: int,
        nombre: str = "Pizza",
        presentacion_codigo: str = "chica",
        presentacion_id: int = 1,
        producto_id: int = 1,
        categoria_id: int = 1,
        categoria_descripcion: str = "Pizzas",
        cantidad: int = 1,
    ):
        pp = MagicMock(id=line_id)
        pp.producto_presentacion.producto.nombre = nombre
        pp.producto_presentacion.producto.categoria.descripcion = (
            categoria_descripcion
        )
        pp.producto_presentacion.presentacion.codigo = presentacion_codigo
        pp.producto_presentacion.id_producto = producto_id
        pp.producto_presentacion.id_presentacion = presentacion_id
        pp.producto_presentacion.producto.id_categoria_producto = categoria_id
        pp.producto_presentacion.producto.activo = True
        pp.producto_presentacion.producto.disponible = True
        pp.producto_presentacion.presentacion.activo = True
        pp.producto_presentacion.activo = True
        pp.id_producto_presentacion = presentation_id
        pp.cantidad = cantidad
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


class ModificarProductoCategoryProjectionTest(unittest.TestCase):
    """Verify the order-line catalog now projects the eager-loaded
    category description as ``categoria_nombre`` instead of ``None``.

    The repository already eager-loads ``producto.categoria`` via the
    existing source-line query. The source catalog MUST surface that
    description so the shared recognizer can distinguish category
    tokens like ``pizza`` / ``empanada`` from required product tokens.
    """

    @staticmethod
    def _make_order_line(
        *,
        pedido_producto_id: int,
        presentacion_id: int,
        producto_id: int,
        presentacion_codigo: str,
        presentacion_descripcion: str,
        producto_nombre: str,
        categoria_id: int,
        categoria_descripcion: str,
        cantidad: int,
    ):
        presentacion = MagicMock(
            codigo=presentacion_codigo,
            descripcion=presentacion_descripcion,
            activo=True,
        )
        producto = MagicMock(
            nombre=producto_nombre,
            id_categoria_producto=categoria_id,
            activo=True,
            disponible=True,
        )
        producto.categoria = MagicMock(descripcion=categoria_descripcion)
        producto_presentacion = MagicMock(
            id_producto=producto_id,
            id_presentacion=presentacion_id,
            activo=True,
        )
        producto_presentacion.producto = producto
        producto_presentacion.presentacion = presentacion
        pp = MagicMock(
            id=pedido_producto_id,
            id_producto_presentacion=100 + pedido_producto_id,
            cantidad=cantidad,
        )
        pp.producto_presentacion = producto_presentacion
        return pp

    def test_order_line_catalog_projects_category_descripcion(self):
        mozzarella_grande = self._make_order_line(
            pedido_producto_id=1,
            presentacion_id=11,
            producto_id=21,
            presentacion_codigo="grande",
            presentacion_descripcion="Grande",
            producto_nombre="Mozzarella",
            categoria_id=31,
            categoria_descripcion="Pizzas",
            cantidad=1,
        )
        verdura = self._make_order_line(
            pedido_producto_id=2,
            presentacion_id=12,
            producto_id=22,
            presentacion_codigo="unidad",
            presentacion_descripcion="Unidad",
            producto_nombre="Verdura",
            categoria_id=32,
            categoria_descripcion="Empanadas",
            cantidad=2,
        )

        catalog = _build_order_line_catalog([mozzarella_grande, verdura])

        self.assertEqual(len(catalog), 2)
        nombres = {entry["categoria_nombre"] for entry in catalog}
        self.assertEqual(nombres, {"Pizzas", "Empanadas"})
        for entry in catalog:
            self.assertNotIn(
                None,
                [entry["categoria_nombre"]],
                "categoria_nombre must come from the eager-loaded category",
            )
        by_id = {entry["pedido_producto_id"]: entry for entry in catalog}
        self.assertEqual(by_id[1]["categoria_nombre"], "Pizzas")
        self.assertEqual(by_id[2]["categoria_nombre"], "Empanadas")
        self.assertEqual(by_id[1]["pedido_producto_id"], 1)
        self.assertEqual(by_id[2]["pedido_producto_id"], 2)

    @patch.object(recognizer_module, "ProductoQueryService")
    @patch.object(recognizer_module, "PedidoProductoService")
    def test_recognize_threads_category_to_recognizer(
        self, pp_service_cls, catalog_cls
    ):
        mozzarella_grande = self._make_order_line(
            pedido_producto_id=10,
            presentacion_id=1,
            producto_id=21,
            presentacion_codigo="grande",
            presentacion_descripcion="Grande",
            producto_nombre="Mozzarella",
            categoria_id=31,
            categoria_descripcion="Pizzas",
            cantidad=1,
        )
        verdura = self._make_order_line(
            pedido_producto_id=11,
            presentacion_id=2,
            producto_id=99,
            presentacion_codigo="unidad",
            presentacion_descripcion="Unidad",
            producto_nombre="Verdura",
            categoria_id=32,
            categoria_descripcion="Empanadas",
            cantidad=2,
        )

        service = MagicMock()
        service.list_by_pedido.return_value = [mozzarella_grande, verdura]
        pp_service_cls.return_value = service

        catalog_service = MagicMock()
        catalog_service.list_recognizer_catalog.return_value = []
        catalog_cls.return_value = catalog_service

        captured: dict = {}

        def _capture(message, catalog, *, intent_metadata=None):
            if catalog and "captured" not in captured:
                captured["catalog"] = list(catalog)
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(recognizer_module, "detectar_productos", side_effect=_capture):
            db = MagicMock(spec=DatabaseSession)
            conversation_session = MagicMock(spec=ConversationSession)
            conversation_session.id_pedido = 7
            conversation_session.id_comercio = 1

            recognize_modificar_producto(
                db,
                conversation_session,
                "cambia una pizza de mozzarella grande por una empanada de carne",
            )

        categorias = {entry["categoria_nombre"] for entry in captured["catalog"]}
        self.assertEqual(categorias, {"Pizzas", "Empanadas"})
        for entry in captured["catalog"]:
            self.assertNotIn(
                None,
                [entry["categoria_nombre"]],
                "categoria_nombre must come from the eager-loaded category",
            )


class ModificarProductoPizzaMozzarellaOwnLinesTest(unittest.TestCase):
    """Drive ``recognize_modificar_producto`` through the real shared
    fuzzy recognizer configured via the module wrapper.

    The factory recognizer is replaced with a real
    ``FuzzyProductRecognizer`` instance via the existing
    ``recognizer_module._product_recognizer`` module-level symbol;
    the wrapper ``recognizer_module.detectar_productos`` continues to
    be the production callable. The test verifies that the catalog
    built with eager-loaded ``categoria_nombre`` produces the
    effective source candidates surfaced as ``source_candidate_ids``.
    """

    def _owned_lines(self) -> list[MagicMock]:
        return [
            ModificarProductoCategoryProjectionTest._make_order_line(
                pedido_producto_id=101,
                presentacion_id=1,
                producto_id=201,
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                producto_nombre="Mozzarella",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
            ModificarProductoCategoryProjectionTest._make_order_line(
                pedido_producto_id=102,
                presentacion_id=2,
                producto_id=201,
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                producto_nombre="Mozzarella",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
            ModificarProductoCategoryProjectionTest._make_order_line(
                pedido_producto_id=103,
                presentacion_id=3,
                producto_id=202,
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                producto_nombre="Napolitana",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
        ]

    def _run_recognizer(self, owned_lines, message, destination_catalog=None):
        """Run ``recognize_modificar_producto`` with the real shared
        fuzzy recognizer controlled via the module wrapper. Returns
        the recognizer result dict.
        """
        db = MagicMock(spec=DatabaseSession)
        conversation_session = MagicMock(spec=ConversationSession)
        conversation_session.id_pedido = 7
        conversation_session.id_comercio = 1

        with _patched_real_fuzzy(), patch.object(
            recognizer_module, "PedidoProductoService"
        ) as pp_service_cls, patch.object(
            recognizer_module, "ProductoQueryService"
        ) as catalog_cls:
            pp_service = MagicMock()
            pp_service.list_by_pedido.return_value = owned_lines
            pp_service_cls.return_value = pp_service

            catalog_service = MagicMock()
            catalog_service.list_recognizer_catalog.return_value = (
                destination_catalog if destination_catalog is not None else []
            )
            catalog_cls.return_value = catalog_service

            return recognize_modificar_producto(
                db, conversation_session, message
            )

    def test_pizza_mozzarella_grande_resolves_only_owned_grande(self):
        """``pizza de mozzarella grande`` MUST surface only the
        Mozzarella Grande own line as ``source_candidate_ids``.
        """
        result = self._run_recognizer(
            self._owned_lines(),
            "cambia una pizza de mozzarella grande por una empanada de verdura",
        )

        self.assertEqual(result["source_candidate_ids"], [101])
        self.assertEqual(result["source_pp_id"], 101)
        self.assertNotIn(102, result["source_candidate_ids"])
        self.assertNotIn(103, result["source_candidate_ids"])

    def test_pizza_mozzarella_returns_only_two_mozzarella_lines(self):
        """``pizza de mozzarella`` MUST surface exactly the two own
        Mozzarella line IDs (Grande and Chica) and exclude the
        Napolitana line that is foreign to the source product.
        """
        result = self._run_recognizer(
            self._owned_lines(),
            "cambia una pizza de mozzarella por una empanada de verdura",
        )

        self.assertEqual(set(result["source_candidate_ids"]), {101, 102})
        self.assertIsNone(result["source_pp_id"])
        self.assertNotIn(103, result["source_candidate_ids"])

    def test_empanada_de_verdura_resolves_only_verdura(self):
        """``empanada de verdura`` MUST surface only the Verdura own
        line as ``source_candidate_ids``.
        """
        empanada = ModificarProductoCategoryProjectionTest._make_order_line(
            pedido_producto_id=201,
            presentacion_id=10,
            producto_id=301,
            presentacion_codigo="unidad",
            presentacion_descripcion="Unidad",
            producto_nombre="Verdura",
            categoria_id=401,
            categoria_descripcion="Empanadas",
            cantidad=1,
        )

        result = self._run_recognizer(
            [empanada],
            "cambia una empanada de verdura por una empanada de carne",
        )

        self.assertEqual(result["source_candidate_ids"], [201])
        self.assertEqual(result["source_pp_id"], 201)

    def test_source_absent_from_draft_yields_no_candidate(self):
        """A category-qualified source product that is absent from the
        active draft MUST surface no source candidate through the
        wrapper-based recognizer flow.
        """
        result = self._run_recognizer(
            self._owned_lines(),
            "cambia una empanada de carne por una empanada de verdura",
        )

        self.assertEqual(result["source_candidate_ids"], [])
        self.assertIsNone(result["source_pp_id"])
        self.assertNotIn(101, result["source_candidate_ids"])
        self.assertNotIn(102, result["source_candidate_ids"])
        self.assertNotIn(103, result["source_candidate_ids"])


class ModificarProductoCategoryBoundaryTest(unittest.TestCase):
    """Recognizer and initial orchestrator must not own transaction
    control over the candidates they surface for category-qualified
    source candidates.
    """

    def test_recognizer_module_does_not_commit(self):
        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.begin",
            "db.close",
            "session.commit",
            "session.rollback",
            "session.flush",
            "session.begin",
            "session.close",
            "session.refresh",
            ".commit()",
            ".rollback()",
            ".flush()",
            ".refresh()",
            ".begin()",
            ".close()",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
