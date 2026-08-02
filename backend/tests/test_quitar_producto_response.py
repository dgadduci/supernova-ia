import importlib
import unittest
from unittest.mock import MagicMock

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.responses import (
    quitar_producto_response as response_module,
)
from backend.intents.responses.quitar_producto_response import (
    build_quitar_producto_response,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _intent(status: str, **kwargs) -> ProcessedIntent:
    literal_status: str = (
        status
        if status in {"pending_resolution", "ready", "executed", "rejected", "failed"}
        else "pending_resolution"
    )
    base: dict = {
        "intent": "quitar_producto",
        "source_text": "x",
        "status": literal_status,
        "recognizer": "recognizer_quitar_producto",
        "handler": "quitar_producto",
    }
    base.update(kwargs)
    return ProcessedIntent(**base)


def _pp_label(pp_id: int, nombre: str, codigo: str) -> MagicMock:
    pp = MagicMock(id=pp_id)
    pp_assoc = pp.producto_presentacion
    presentacion = pp_assoc.presentacion
    presentacion.codigo = codigo
    presentacion.descripcion = codigo
    producto = pp_assoc.producto
    producto.nombre = nombre
    return pp


class QuitarProductoResponseBuilderPendingTest(unittest.TestCase):
    def test_two_candidates_render_as_documented(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pp_a = _pp_label(10, "Pizza de Muzzarella Grande", "grande")
        pp_b = _pp_label(11, "Pizza Napolitana Grande", "grande")

        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = [pp_a, pp_b]
            intent = _intent(
                "pending_resolution",
                candidate_ids=[10, 11],
            )
            result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "¿Cuál querés quitar: Pizza de Muzzarella Grande (grande) o Pizza Napolitana Grande (grande)?",
        )
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.status, "pending_resolution")

    def test_three_candidates_join_with_o(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pps = [
            _pp_label(10, "A", "x"),
            _pp_label(11, "B", "x"),
            _pp_label(12, "C", "x"),
        ]
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = pps
            intent = _intent("pending_resolution", candidate_ids=[10, 11, 12])
            result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(result.message, "¿Cuál querés quitar: A (x) o B (x) o C (x)?")


class QuitarProductoResponseBuilderExecutedTest(unittest.TestCase):
    def test_partial_execution_renders_partial_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "pedido_producto_id": 1,
                "cantidad_removida": 2,
                "cantidad_restante": 1,
                "producto_nombre": "Empanadas de carne",
                "presentacion_codigo": "docena",
                "presentacion_descripcion": "Docena",
                "linea_eliminada": False,
            },
        )

        result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Quité 2 Empanadas de carne (docena). Queda 1 en tu pedido.",
        )
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.status, "executed")

    def test_complete_execution_renders_complete_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "pedido_producto_id": 1,
                "cantidad_removida": 3,
                "cantidad_restante": 0,
                "producto_nombre": "Pizza de Muzzarella",
                "presentacion_codigo": "grande",
                "presentacion_descripcion": "Grande",
                "linea_eliminada": True,
            },
        )

        result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Quité Pizza de Muzzarella (grande) de tu pedido.",
        )


class QuitarProductoResponseBuilderRejectedTest(unittest.TestCase):
    def test_excess_quantity_renders_excess_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={
                "pedido_producto_id": 1,
                "cantidad_actual": 2,
                "producto_nombre": "Empanadas de carne",
                "presentacion_codigo": "docena",
                "presentacion_descripcion": "Docena",
            },
        )

        result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Solo tenés 2 Empanadas de carne (docena) en el pedido.",
        )

    def test_absent_product_renders_absent_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent("rejected", resolved_data={})

        result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(result.message, "Ese producto no está en tu pedido.")


class QuitarProductoResponseBuilderFailedTest(unittest.TestCase):
    def test_failed_renders_failed_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent("failed")

        result = build_quitar_producto_response(db, session, intent)

        self.assertEqual(result.message, "No pude procesar tu pedido. Intentá de nuevo en un momento.")
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.status, "failed")


class QuitarProductoResponseBuilderMetadataTest(unittest.TestCase):
    def test_intent_and_status_preserved_for_every_outcome(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        for status in ("pending_resolution", "executed", "rejected", "failed"):
            kwargs = {"resolved_data": {}}
            if status == "executed":
                kwargs["resolved_data"] = {
                    "cantidad_removida": 1,
                    "cantidad_restante": 0,
                    "producto_nombre": "X",
                    "presentacion_codigo": "y",
                    "presentacion_descripcion": "Y",
                    "linea_eliminada": True,
                }
            intent = _intent(status, **kwargs)
            result = build_quitar_producto_response(db, session, intent)
            self.assertEqual(result.intent, "quitar_producto")
            self.assertEqual(result.status, status)


class QuitarProductoResponseBuilderBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_llm(self):
        importlib.reload(response_module)
        with open(response_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "from backend.llm",
            "QueryLlm",
            "import requests",
            "from requests",
            "from backend.routers",
            "from backend.dependencies",
            "backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            response_module.__all__,
            ["build_quitar_producto_response"],
        )


if __name__ == "__main__":
    unittest.main()