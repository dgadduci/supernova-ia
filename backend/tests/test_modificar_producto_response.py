import importlib
import unittest
from unittest.mock import MagicMock

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.responses import (
    modificar_producto_response as response_module,
)
from backend.intents.responses.modificar_producto_response import (
    build_modificar_producto_response,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _intent(status: str, **kwargs) -> ProcessedIntent:
    literal_status = status
    base: dict = {
        "intent": "modificar_producto",
        "source_text": "x",
        "status": literal_status,
        "recognizer": "modificar_producto_recognizer",
        "handler": "modificar_producto",
    }
    base.update(kwargs)
    return ProcessedIntent(**base)


class ModificarProductoResponseBuilderPendingSourceTest(unittest.TestCase):
    def test_two_source_candidates_render_with_o(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pp_a = MagicMock(id=10)
        pp_a.producto_presentacion.producto.nombre = "Pizza de Muzzarella Chica"
        pp_a.producto_presentacion.presentacion.codigo = "chica"
        pp_b = MagicMock(id=11)
        pp_b.producto_presentacion.producto.nombre = "Pizza Napolitana Chica"
        pp_b.producto_presentacion.presentacion.codigo = "chica"

        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = [pp_a, pp_b]
            intent = _intent(
                "pending_resolution",
                stage="source_selection",
                resolved_data={
                    "source_candidate_ids": [10, 11],
                    "destination_candidate_ids": [],
                },
            )
            result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "¿Cuál producto querés cambiar: Pizza de Muzzarella Chica (chica) o Pizza Napolitana Chica (chica)?",
        )
        self.assertEqual(result.intent, "modificar_producto")
        self.assertEqual(result.status, "pending_resolution")

    def test_three_source_candidates_join_with_o(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pps = []
        for pid, name in [(10, "A"), (11, "B"), (12, "C")]:
            pp = MagicMock(id=pid)
            pp.producto_presentacion.producto.nombre = name
            pp.producto_presentacion.presentacion.codigo = "x"
            pps.append(pp)

        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = pps
            intent = _intent(
                "pending_resolution",
                stage="source_selection",
                resolved_data={
                    "source_candidate_ids": [10, 11, 12],
                    "destination_candidate_ids": [],
                },
            )
            result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "¿Cuál producto querés cambiar: A (x), B (x) o C (x)?",
        )


class ModificarProductoResponseBuilderPendingDestinationTest(unittest.TestCase):
    def test_two_destination_candidates_render_with_o(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        catalog_entries = [
            {
                "producto_presentacion_id": 200,
                "producto_nombre": "Pizza de Muzzarella Grande",
                "presentacion_codigo": "grande",
            },
            {
                "producto_presentacion_id": 201,
                "producto_nombre": "Pizza Napolitana Grande",
                "presentacion_codigo": "grande",
            },
        ]
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            response_module, "ProductoQueryService"
        ) as catalog_cls:
            catalog_cls.return_value.list_presentaciones_by_ids.return_value = catalog_entries
            intent = _intent(
                "pending_resolution",
                stage="destination_selection",
                resolved_data={
                    "source_candidate_ids": [10],
                    "destination_candidate_ids": [200, 201],
                },
            )
            result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "¿Cuál querés como reemplazo: Pizza de Muzzarella Grande (grande) o Pizza Napolitana Grande (grande)?",
        )


class ModificarProductoResponseBuilderExecutedTest(unittest.TestCase):
    def test_full_line_swap_renders_full_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "pedido_producto_origen_id": 1,
                "producto_presentacion_destino_id": 2,
                "producto_origen_nombre": "Empanadas de Verdura",
                "presentacion_origen": "Unidad",
                "producto_destino_nombre": "Empanadas de Carne Picante",
                "presentacion_destino": "Unidad",
                "cantidad_modificada": 4,
                "cantidad_origen_restante": 0,
                "cantidad_destino_final": 4,
                "origen_eliminado": True,
                "destino_creado": True,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.",
        )

    def test_full_line_swap_omitted_quantity_uses_full_source_quantity(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "producto_origen_nombre": "Empanadas de Verdura",
                "producto_destino_nombre": "Empanadas de Carne Picante",
                "cantidad_modificada": 4,
                "cantidad_origen_restante": 0,
                "cantidad_destino_final": 4,
                "origen_eliminado": True,
                "destino_creado": True,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.",
        )

    def test_partial_renders_partial_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "producto_origen_nombre": "Empanadas de Verdura",
                "producto_destino_nombre": "Empanadas de Carne Picante",
                "cantidad_modificada": 2,
                "cantidad_origen_restante": 3,
                "cantidad_destino_final": 2,
                "origen_eliminado": False,
                "destino_creado": True,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 2 Empanadas de Verdura por 2 de Empanadas de Carne Picante. Quedan 3 Empanadas de Verdura.",
        )

    def test_consolidated_renders_consolidated_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "producto_origen_nombre": "Empanadas de Verdura",
                "producto_destino_nombre": "Empanadas de Carne Picante",
                "cantidad_modificada": 4,
                "cantidad_origen_restante": 0,
                "cantidad_destino_final": 6,
                "origen_eliminado": True,
                "destino_creado": False,
                "cantidad_destino_modificada": 4,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 4 Empanadas de Verdura por Empanadas de Carne Picante. Ahora tenés 6 Empanadas de Carne Picante.",
        )

    def test_distinct_quantity_renders_both_values(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "producto_origen_nombre": "Pizza Napolitana",
                "producto_destino_nombre": "Pizza Mozzarella",
                "cantidad_modificada": 2,
                "cantidad_destino_modificada": 1,
                "cantidad_origen_restante": 5,
                "cantidad_destino_final": 1,
                "origen_eliminado": False,
                "destino_creado": True,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 2 Pizza Napolitana por 1 de Pizza Mozzarella. Quedan 5 Pizza Napolitana.",
        )

    def test_distinct_quantity_consolidated_renders_both_values(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "executed",
            resolved_data={
                "producto_origen_nombre": "Pizza Napolitana",
                "producto_destino_nombre": "Pizza Mozzarella",
                "cantidad_modificada": 2,
                "cantidad_destino_modificada": 1,
                "cantidad_origen_restante": 0,
                "cantidad_destino_final": 3,
                "origen_eliminado": True,
                "destino_creado": False,
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Cambié 2 Pizza Napolitana por 1 de Pizza Mozzarella. Ahora tenés 3 Pizza Mozzarella.",
        )


class ModificarProductoResponseBuilderRejectedTest(unittest.TestCase):
    def test_excess_quantity_renders_excess_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={
                "reason": "quantity_exceeds_source",
                "cantidad_actual": 2,
                "producto_origen_nombre": "Empanadas de Verdura",
                "presentacion_origen": "Unidad",
            },
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Solo tenés 2 Empanadas de Verdura para cambiar. Tu pedido no fue modificado.",
        )

    def test_source_absent_renders_absent_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "source_not_in_pedido"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(result.message, "Ese producto no está en tu pedido.")

    def test_destination_unavailable_renders_unavailable_message_with_pedido_confirmation(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "destination_unavailable"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "El producto de reemplazo no está disponible. Tu pedido no fue modificado.",
        )

    def test_destination_price_missing_renders_unavailable_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "destination_price_missing"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "El producto de reemplazo no está disponible. Tu pedido no fue modificado.",
        )

    def test_no_destination_candidates_renders_unknown_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "no_destination_candidates"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "No encontré el producto de reemplazo. Tu pedido no fue modificado.",
        )

    def test_equivalent_modification_renders_equivalent_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "equivalent_modification"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "Ese producto ya tiene esa presentación en tu pedido.",
        )

    def test_invalid_destination_quantity_renders_invalid_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent(
            "rejected",
            resolved_data={"reason": "invalid_destination_quantity"},
        )

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "La cantidad del producto de reemplazo no es válida. Tu pedido no fue modificado.",
        )


class ModificarProductoResponseBuilderFailedTest(unittest.TestCase):
    def test_failed_renders_failed_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _intent("failed")

        result = build_modificar_producto_response(db, session, intent)

        self.assertEqual(
            result.message,
            "No pude procesar tu pedido. Intentá de nuevo en un momento.",
        )
        self.assertEqual(result.intent, "modificar_producto")
        self.assertEqual(result.status, "failed")


class ModificarProductoResponseBuilderMetadataTest(unittest.TestCase):
    def test_intent_and_status_preserved_for_every_outcome(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        for status in ("pending_resolution", "executed", "rejected", "failed"):
            kwargs = {"resolved_data": {}}
            if status == "executed":
                kwargs["resolved_data"] = {
                    "producto_origen_nombre": "X",
                    "presentacion_origen": "y",
                    "producto_destino_nombre": "X",
                    "presentacion_destino": "z",
                    "cantidad_modificada": 1,
                    "cantidad_origen_restante": 0,
                    "cantidad_destino_final": 1,
                    "origen_eliminado": True,
                    "destino_creado": True,
                }
            if status == "pending_resolution":
                kwargs["stage"] = "source_selection"  # type: ignore[assignment]
                kwargs["resolved_data"] = {
                    "source_candidate_ids": [],
                    "destination_candidate_ids": [],
                }
            intent = _intent(status, **kwargs)
            result = build_modificar_producto_response(db, session, intent)
            self.assertEqual(result.intent, "modificar_producto")
            self.assertEqual(result.status, status)


class ModificarProductoResponseBuilderBoundariesTest(unittest.TestCase):
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
            "from fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            response_module.__all__,
            ["build_modificar_producto_response"],
        )


if __name__ == "__main__":
    unittest.main()
