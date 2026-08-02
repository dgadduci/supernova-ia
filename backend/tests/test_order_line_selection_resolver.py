import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import (
    order_line_selection_resolver as resolver_module,
)
from backend.intents.context.order_line_selection_resolver import (
    resolve_order_line_selection,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _active_intent(candidate_ids: list[int]) -> ProcessedIntent:
    return ProcessedIntent(
        intent="quitar_producto",
        source_text="quitá una pizza",
        status="pending_resolution",
        recognizer="recognizer_quitar_producto",
        handler="quitar_producto",
        resolved_data={},
        requirements=[
            RequirementState(name="pedido_producto_id", status="pending", value=None),
            RequirementState(name="cantidad", status="pending", value=None),
        ],
        candidate_ids=list(candidate_ids),
    )


class ResolveOrderLineSelectionNarrowingTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_refinement_to_single_returns_ready(self, recognize):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 102}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102, 103])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la de muzzarella", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["pedido_producto_id"], 102)
        req_names = {r.name: r.status for r in result.requirements}
        self.assertEqual(req_names.get("pedido_producto_id"), "completed")

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_refinement_to_subset_keeps_pending(self, recognize):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {
                    "texto_origen": "la grande",
                    "productos": [
                        {"pedido_producto_id": 102},
                        {"pedido_producto_id": 104},
                    ],
                }
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102, 103, 104, 105])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la grande", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(set(result.candidate_ids), {102, 104})
        self.assertNotIn(101, result.candidate_ids)
        self.assertNotIn(103, result.candidate_ids)
        self.assertNotIn(105, result.candidate_ids)


class ResolveOrderLineSelectionRejectionTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_invalid_candidate_returns_rejected_without_mutation(
        self, recognize
    ):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 999}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "x", active)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.candidate_ids, [101, 102])

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_no_match_keeps_active_unchanged(self, recognize):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "x"}],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "gibberish", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [101, 102])


class ResolveOrderLineSelectionBoundariesTest(unittest.TestCase):
    def test_module_does_not_broaden_to_commerce_catalog(self):
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("list_recognizer_catalog", source)
        self.assertNotIn("from backend.services.producto_query_service", source)

    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(resolver_module)
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "from sqlalchemy import select",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "backend.old_project",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            resolver_module.__all__,
            ["resolve_order_line_selection"],
        )


if __name__ == "__main__":
    unittest.main()