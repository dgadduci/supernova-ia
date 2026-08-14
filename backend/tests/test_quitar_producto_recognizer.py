import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers import (
    quitar_producto_recognizer as recognizer_module,
)
from backend.intents.recognizers.quitar_producto_recognizer import (
    _build_order_line_catalog,
    recognize_quitar_producto,
)
from backend.models.session import Session as ConversationSession
from backend.recognizers.product_recognizer import detectar_productos


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
    presentacion_activo: bool = True,
    producto_activo: bool = True,
    producto_disponible: bool = True,
    producto_presentacion_activo: bool = True,
) -> MagicMock:
    """Build a MagicMock ``PedidoProducto`` with eager-loaded
    presentation/product/category."""
    presentacion = MagicMock(
        codigo=presentacion_codigo,
        descripcion=presentacion_descripcion,
        activo=presentacion_activo,
    )
    producto = MagicMock(
        nombre=producto_nombre,
        id_categoria_producto=categoria_id,
        activo=producto_activo,
        disponible=producto_disponible,
    )
    producto.categoria = MagicMock(descripcion=categoria_descripcion)
    producto_presentacion = MagicMock(
        id_producto=producto_id,
        id_presentacion=presentacion_id,
        activo=producto_presentacion_activo,
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


class QuitarProductoCategoryProjectionTest(unittest.TestCase):
    """Verify the order-line catalog now projects the eager-loaded
    category description as ``categoria_nombre`` instead of ``None``.
    """

    def test_order_line_catalog_projects_category_descripcion(self):
        pizza_grande = _make_order_line(
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
        pizza_chica = _make_order_line(
            pedido_producto_id=2,
            presentacion_id=12,
            producto_id=21,
            presentacion_codigo="chica",
            presentacion_descripcion="Chica",
            producto_nombre="Mozzarella",
            categoria_id=31,
            categoria_descripcion="Pizzas",
            cantidad=1,
        )
        napolitana_chica = _make_order_line(
            pedido_producto_id=3,
            presentacion_id=13,
            producto_id=22,
            presentacion_codigo="chica",
            presentacion_descripcion="Chica",
            producto_nombre="Napolitana",
            categoria_id=31,
            categoria_descripcion="Pizzas",
            cantidad=1,
        )

        catalog = _build_order_line_catalog([pizza_grande, pizza_chica, napolitana_chica])

        self.assertEqual(len(catalog), 3)
        nombres = {entry["categoria_nombre"] for entry in catalog}
        self.assertEqual(nombres, {"Pizzas"})
        for entry in catalog:
            self.assertNotIn(
                None,
                [entry["categoria_nombre"]],
                "categoria_nombre must come from the eager-loaded category",
            )

    @patch.object(recognizer_module, "PedidoProductoService")
    def test_recognize_quitar_producto_threads_category_to_recognizer(
        self, service_cls
    ):
        pizza_grande = _make_order_line(
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
        empanada = _make_order_line(
            pedido_producto_id=11,
            presentacion_id=2,
            producto_id=99,
            presentacion_codigo="unidad",
            presentacion_descripcion="Unidad",
            producto_nombre="Empanada",
            categoria_id=32,
            categoria_descripcion="Empanadas",
            cantidad=2,
        )

        service = MagicMock()
        service.list_by_pedido.return_value = [pizza_grande, empanada]
        service_cls.return_value = service

        captured: dict = {}

        def _capture(message, catalog, *, intent_metadata=None):
            captured["catalog"] = list(catalog)
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

        with patch.object(recognizer_module, "detectar_productos", side_effect=_capture):
            db = MagicMock(spec=DatabaseSession)
            session = MagicMock(spec=ConversationSession)
            session.id_pedido = 7

            recognize_quitar_producto(db, session, "una pizza de mozzarella")

        categorias = {entry["categoria_nombre"] for entry in captured["catalog"]}
        self.assertEqual(categorias, {"Pizzas", "Empanadas"})


class QuitarProductoPizzaMozzarellaOwnLinesTest(unittest.TestCase):
    """Use the real ``detectar_productos`` (and therefore the real
    shared fuzzy product recognizer) against the order-line catalog
    built from three owned lines in ``Pizzas``:

    - Mozzarella Grande
    - Mozzarella Chica
    - Napolitana Chica

    The customer request ``una pizza de mozzarella`` MUST return only
    the two Mozzarella lines; the Napolitana line MUST NOT appear, and
    no fallback to a broader commerce catalog is allowed.
    """

    def _owned_lines(self) -> list[MagicMock]:
        return [
            _make_order_line(
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
            _make_order_line(
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
            _make_order_line(
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

    def _owned_catalog(self) -> list[dict]:
        return _build_order_line_catalog(self._owned_lines())

    def _candidate_ids(self, result: dict) -> set[int]:
        encontrados_ids = {
            int(entry["pedido_producto_id"]) for entry in result["encontrados"]
        }
        posibles_ids: set[int] = set()
        for group in result["encontrados_posibles"]:
            if group.get("kind") == "category":
                continue
            for product in group.get("productos", []):
                pid = product.get("pedido_producto_id")
                if pid is not None:
                    posibles_ids.add(int(pid))
        return encontrados_ids | posibles_ids

    @patch.object(recognizer_module, "PedidoProductoService")
    def test_pizza_mozzarella_returns_only_two_mozzarella_lines(self, service_cls):
        service = MagicMock()
        service.list_by_pedido.return_value = self._owned_lines()
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = recognize_quitar_producto(
            db, session, "quiero quitar una pizza de mozzarella"
        )

        candidate_ids = self._candidate_ids(result)
        self.assertIn(101, candidate_ids)
        self.assertIn(102, candidate_ids)
        self.assertNotIn(103, candidate_ids)
        self.assertNotIn(
            999,
            candidate_ids,
            "no commerce-catalog line should be widened into the set",
        )
        self.assertEqual(
            result["no_encontrados"],
            [],
            "the two owned Mozzarella lines must produce a recognised set",
        )

    def test_real_fuzzy_recognizer_with_owned_catalog_matches_two_lines(self):
        catalog = self._owned_catalog()
        result = detectar_productos(
            "quiero quitar una pizza de mozzarella", catalog
        )
        candidate_ids = self._candidate_ids(result)
        self.assertIn(101, candidate_ids)
        self.assertIn(102, candidate_ids)
        self.assertNotIn(103, candidate_ids)
        self.assertEqual(result["no_encontrados"], [])


if __name__ == "__main__":
    unittest.main()