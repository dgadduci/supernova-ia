import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import (
    product_modification_resolver as resolver_module,
)
from backend.intents.context.product_modification_resolver import (
    resolve_product_modification,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _pending_intent(
    stage: str,
    source_candidate_ids: list[int],
    destination_candidate_ids: list[int],
    *,
    cantidad: int | None = None,
) -> ProcessedIntent:
    resolved_data: dict = {
        "source_candidate_ids": list(source_candidate_ids),
        "destination_candidate_ids": list(destination_candidate_ids),
    }
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    return ProcessedIntent(
        intent="modificar_producto",
        source_text="x",
        status="pending_resolution",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        stage=stage,  # type: ignore[arg-type]
        resolved_data=resolved_data,
        candidate_ids=[],
    )


class ResolveProductModificationSourceSelectionTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_refinement_narrows_to_one(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "source_selection", [11, 12], [200, 201], cantidad=2
        )

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "destination_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11])
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200, 201]
        )
        self.assertEqual(result.resolved_data["cantidad"], 2)

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_refinement_to_unique_with_unique_dest_returns_ready(
        self, recognizer
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200])

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 11
        )
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 200
        )

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_invalid_source_id_returns_rejected(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200])

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 99}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "otra cosa", active)

        self.assertEqual(result.status, "rejected")

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_keeps_ambiguous_after_refinement(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200, 201])

        recognizer.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {"productos": [{"pedido_producto_id": 11}, {"pedido_producto_id": 12}]}
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "pizza", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "source_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11, 12])


class ResolveProductModificationDestinationSelectionTest(unittest.TestCase):
    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_destination_refinement_narrows_to_one(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "destination_selection", [11], [200, 201, 202], cantidad=3
        )

        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 200, "producto_nombre": "A", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 201, "producto_nombre": "B", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 202, "producto_nombre": "C", "presentacion_codigo": "g"},
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 201}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(db, session, "la B", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 11
        )
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 201
        )
        self.assertEqual(result.resolved_data["cantidad"], 3)

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_invalid_destination_returns_rejected(self, detector, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("destination_selection", [11], [200, 201])

        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 200, "producto_nombre": "A", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 201, "producto_nombre": "B", "presentacion_codigo": "g"},
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 999}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(db, session, "x", active)

        self.assertEqual(result.status, "rejected")


class ResolveProductModificationPreservationTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_cantidad_preserved_across_turns(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200], cantidad=3)

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.resolved_data["cantidad"], 3)


class ResolveProductModificationBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback(self):
        importlib.reload(resolver_module)
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "from backend.llm",
            "from backend.routers",
            "from backend.intents.responses",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            resolver_module.__all__,
            ["resolve_product_modification"],
        )


if __name__ == "__main__":
    unittest.main()
