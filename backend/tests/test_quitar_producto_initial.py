import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration import (
    quitar_producto_initial as orchestrator_module,
)
from backend.intents.orchestration.quitar_producto_initial import (
    process_initial_quitar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _session(id_pedido):
    s = MagicMock(spec=ConversationSession)
    s.id_pedido = id_pedido
    s.context_type = None
    s.pending_intents = None
    return s


class ProcessInitialQuitarProductoMissingPedidoTest(unittest.TestCase):
    @patch.object(orchestrator_module, "recognize_quitar_producto")
    def test_missing_pedido_returns_rejected_without_mutation(self, recognize):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=None)

        result = process_initial_quitar_producto(db, session, "pizza")

        recognize.assert_not_called()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.handler, "quitar_producto")
        self.assertEqual(result.source_text, "pizza")
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class ProcessInitialQuitarProductoUniqueMatchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "execute_quitar_producto")
    @patch.object(orchestrator_module, "recognize_quitar_producto")
    def test_unique_match_returns_ready_then_executes(
        self, recognize, execute_handler
    ):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 42}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": 2,
        }
        execute_handler.side_effect = lambda db, session, intent: intent.model_copy(
            update={"status": "executed"}
        )

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_quitar_producto(db, session, "quitá 2 empanadas")

        execute_handler.assert_called_once()
        ready_arg = execute_handler.call_args.args[2]
        self.assertEqual(ready_arg.status, "ready")
        self.assertEqual(ready_arg.intent, "quitar_producto")
        self.assertEqual(ready_arg.handler, "quitar_producto")
        self.assertEqual(ready_arg.recognizer, "recognizer_quitar_producto")
        self.assertEqual(ready_arg.resolved_data["pedido_producto_id"], 42)
        self.assertEqual(ready_arg.resolved_data["cantidad"], 2)
        req_names = {r.name: r.status for r in ready_arg.requirements}
        self.assertEqual(req_names.get("pedido_producto_id"), "completed")
        self.assertEqual(req_names.get("cantidad"), "completed")
        self.assertEqual(ready_arg.candidate_ids, [])
        self.assertEqual(result.status, "executed")


class ProcessInitialQuitarProductoAmbiguousTest(unittest.TestCase):
    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_quitar_producto")
    def test_ambiguous_match_creates_pending_context(
        self, recognize, set_pending
    ):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {
                    "texto_origen": "pizza",
                    "productos": [
                        {"pedido_producto_id": 10},
                        {"pedido_producto_id": 11},
                        {"pedido_producto_id": 12},
                    ],
                }
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_quitar_producto(db, session, "pizza")

        set_pending.assert_called_once()
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(set(result.candidate_ids), {10, 11, 12})


class ProcessInitialQuitarProductoNoMatchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_quitar_producto")
    def test_no_match_returns_rejected_without_pending(
        self, recognize, set_pending
    ):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "pizza"}],
            "cantidad": None,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_quitar_producto(db, session, "pizza")

        set_pending.assert_not_called()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "quitar_producto")


class ProcessInitialQuitarProductoPizzaMozzarellaPendingTest(unittest.TestCase):
    """Repro the production defect: ``Quiero quitar una pizza de
    mozzarella`` against a draft containing Mozzarella Grande,
    Mozzarella Chica, and Napolitana Chica (all in ``Pizzas``). The
    initial orchestrator MUST persist the existing ``pending_resolution``
    context with exactly the two Mozzarella ``pedido_producto_id``s,
    MUST NOT execute the handler, and MUST NOT own the transaction.
    """

    @patch.object(orchestrator_module, "execute_quitar_producto")
    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_quitar_producto")
    def test_two_mozzarella_lines_create_pending_without_handler(
        self, recognize, set_pending, execute_handler
    ):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {
                    "texto_origen": "una pizza de mozzarella",
                    "productos": [
                        {"pedido_producto_id": 201},
                        {"pedido_producto_id": 202},
                    ],
                }
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_quitar_producto(
            db, session, "quiero quitar una pizza de mozzarella"
        )

        execute_handler.assert_not_called()
        set_pending.assert_called_once()
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.handler, "quitar_producto")
        self.assertEqual(set(result.candidate_ids), {201, 202})
        self.assertNotIn(999, result.candidate_ids)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.begin.assert_not_called()


class ProcessInitialQuitarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(orchestrator_module)
        with open(orchestrator_module.__file__, encoding="utf-8") as fh:
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
            "from backend.dependencies",
            "backend.old_project",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "HTTPException",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            orchestrator_module.__all__,
            ["process_initial_quitar_producto"],
        )


if __name__ == "__main__":
    unittest.main()