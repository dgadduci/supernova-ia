"""Focused tests for the initial `set_observacion_producto` orchestrator.

The orchestrator must:

- return ``rejected`` (no mutation) when ``session.id_pedido`` is
  ``None``;
- return ``ready`` (auto-executed through the dedicated handler) when
  exactly one unique candidate is found;
- return ``pending_resolution`` with ``candidate_ids`` populated and
  persist an ``order_line_selection`` pending context when more than
  one candidate matches;
- return ``rejected`` when the recognizer surfaces zero candidates;
- never import catalog reads, the LLM, the repositories, or HTTP;
- never commit, rollback, flush, refresh, expire, begin, or close.
"""
import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration import (
    set_observacion_producto_initial as orchestrator_module,
)
from backend.intents.orchestration.set_observacion_producto_initial import (
    process_initial_set_observacion_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import EstadoSession, Session as ConversationSession


def _session(
    id_pedido: int | None,
    *,
    session_id: int = 1,
    estado_session: EstadoSession = EstadoSession.ACTIVA,
) -> MagicMock:
    s = MagicMock(spec=ConversationSession)
    s.id = session_id
    s.id_pedido = id_pedido
    s.estado_session = estado_session
    s.context_type = None
    s.pending_intents = None
    return s


class ProcessInitialSetObservacionProductoMissingPedidoTest(unittest.TestCase):
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_missing_pedido_returns_rejected_without_mutation(self, recognize):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=None)

        result = process_initial_set_observacion_producto(
            db, session, "La pizza es sin aceitunas"
        )

        recognize.assert_not_called()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.handler, "set_observacion_producto")
        self.assertEqual(result.source_text, "La pizza es sin aceitunas")
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class ProcessInitialSetObservacionProductoClosedSessionTest(unittest.TestCase):
    """A non-active session must not reach the recognizer nor persist any
    pending context, even when the underlying fuzzy recognizer would have
    produced multiple candidates."""

    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "resolve_context_type")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_closed_session_with_multiple_candidates_returns_rejected(
        self, recognize, resolve_ctx, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7, estado_session=EstadoSession.CERRADA)

        result = process_initial_set_observacion_producto(
            db, session, "pizza es sin aceitunas"
        )

        recognize.assert_not_called()
        resolve_ctx.assert_not_called()
        set_pending.assert_not_called()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.handler, "set_observacion_producto")
        self.assertEqual(result.source_text, "pizza es sin aceitunas")
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_closed_session_short_circuits_before_unique_match(
        self, recognize, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7, estado_session=EstadoSession.CERRADA)

        result = process_initial_set_observacion_producto(
            db, session, "pizza es sin aceitunas"
        )

        recognize.assert_not_called()
        set_pending.assert_not_called()
        self.assertEqual(result.status, "rejected")
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class ProcessInitialSetObservacionProductoUniqueMatchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "execute_set_observacion_producto")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_unique_match_returns_ready_then_executes(
        self, recognize, execute_handler
    ):
        recognize.return_value = {
            "candidate_ids": [42],
            "observation_action": "set",
            "observation_text": "La pizza es sin aceitunas",
            "no_pedido": False,
        }
        execute_handler.side_effect = lambda db, session, intent: intent.model_copy(
            update={"status": "executed"}
        )

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_set_observacion_producto(
            db, session, "La pizza es sin aceitunas"
        )

        execute_handler.assert_called_once()
        ready_arg = execute_handler.call_args.args[2]
        self.assertEqual(ready_arg.status, "ready")
        self.assertEqual(ready_arg.intent, "set_observacion_producto")
        self.assertEqual(ready_arg.handler, "set_observacion_producto")
        self.assertEqual(ready_arg.recognizer, "recognizer_set_observacion_producto")
        self.assertEqual(ready_arg.resolved_data["pedido_producto_id"], 42)
        self.assertEqual(ready_arg.resolved_data["observation_action"], "set")
        self.assertEqual(
            ready_arg.resolved_data["observation_text"],
            "La pizza es sin aceitunas",
        )
        req_names = {r.name: r.status for r in ready_arg.requirements}
        self.assertEqual(req_names.get("pedido_producto_id"), "completed")
        self.assertEqual(req_names.get("observacion"), "completed")
        self.assertEqual(ready_arg.candidate_ids, [])
        self.assertEqual(result.status, "executed")

    @patch.object(orchestrator_module, "execute_set_observacion_producto")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_clear_unique_match_passes_null_to_handler(
        self, recognize, execute_handler
    ):
        recognize.return_value = {
            "candidate_ids": [99],
            "observation_action": "clear",
            "observation_text": "",
            "no_pedido": False,
        }
        execute_handler.side_effect = lambda db, session, intent: intent.model_copy(
            update={"status": "executed"}
        )

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_set_observacion_producto(
            db, session, "Quitar la aclaración de la pizza"
        )

        execute_handler.assert_called_once()
        ready_arg = execute_handler.call_args.args[2]
        self.assertEqual(ready_arg.resolved_data["observation_action"], "clear")
        self.assertNotIn("observation_text", ready_arg.resolved_data)
        self.assertEqual(result.status, "executed")


class ProcessInitialSetObservacionProductoAmbiguousTest(unittest.TestCase):
    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_ambiguous_match_creates_pending_context(self, recognize, set_pending):
        recognize.return_value = {
            "candidate_ids": [10, 11, 12],
            "observation_action": "set",
            "observation_text": "La pizza es sin aceitunas",
            "no_pedido": False,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_set_observacion_producto(
            db, session, "La pizza es sin aceitunas"
        )

        set_pending.assert_called_once()
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(set(result.candidate_ids), {10, 11, 12})
        self.assertEqual(
            result.resolved_data["observation_action"], "set"
        )
        self.assertEqual(
            result.resolved_data["observation_text"],
            "La pizza es sin aceitunas",
        )

    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_ambiguous_clear_keeps_action_for_refinement(
        self, recognize, set_pending
    ):
        recognize.return_value = {
            "candidate_ids": [10, 11],
            "observation_action": "clear",
            "observation_text": "",
            "no_pedido": False,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_set_observacion_producto(
            db, session, "Quitar la aclaración de la pizza"
        )

        set_pending.assert_called_once()
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.resolved_data["observation_action"], "clear")
        self.assertNotIn("observation_text", result.resolved_data)


class ProcessInitialSetObservacionProductoNoMatchTest(unittest.TestCase):
    @patch.object(orchestrator_module, "set_pending_intent")
    @patch.object(orchestrator_module, "recognize_set_observacion_producto")
    def test_no_match_returns_rejected_without_pending(self, recognize, set_pending):
        recognize.return_value = {
            "candidate_ids": [],
            "observation_action": "set",
            "observation_text": "gibberish",
            "no_pedido": False,
        }

        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)

        result = process_initial_set_observacion_producto(
            db, session, "gibberish"
        )

        set_pending.assert_not_called()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "set_observacion_producto")


class ProcessInitialSetObservacionProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(orchestrator_module)
        with open(orchestrator_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
            "db.close",
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
            "from backend.services",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            orchestrator_module.__all__,
            ["process_initial_set_observacion_producto"],
        )


if __name__ == "__main__":
    unittest.main()
