import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration import (
    modificar_producto_initial as initial_module,
)
from backend.intents.orchestration.modificar_producto_initial import (
    process_initial_modificar_producto,
)
from backend.models.session import Session as ConversationSession


class ProcessInitialModificarProductoMissingPedidoTest(unittest.TestCase):
    def test_missing_pedido_returns_rejected(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        result = process_initial_modificar_producto(db, session, "cambiá algo")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "modificar_producto")


class ProcessInitialModificarProductoReadyTest(unittest.TestCase):
    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_domains_return_ready(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza chica por una grande"
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.intent, "modificar_producto")
        execute_handler.assert_called_once()
        set_pending.assert_not_called()

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_with_cantidad_preserves_it(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={"cantidad": 2},
            requirements=[],
            candidate_ids=[],
        )

        result = process_initial_modificar_producto(
            db, session, "cambiá 2 chicas por 2 grandes"
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data.get("cantidad"), 2)

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_with_paired_cantidad_destino(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
            "cantidad_destino": 1,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={"cantidad": 2, "cantidad_destino": 1},
            requirements=[],
            candidate_ids=[],
        )

        process_initial_modificar_producto(
            db, session, "cambiar 2 napolitanas por una muzza"
        )

        args, _ = execute_handler.call_args
        ready_intent = args[2]
        self.assertEqual(ready_intent.resolved_data["cantidad"], 2)
        self.assertEqual(ready_intent.resolved_data["cantidad_destino"], 1)


class ProcessInitialModificarProductoPendingTest(unittest.TestCase):
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_ambiguous_source_returns_pending_source_selection(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11, 12],
            "destination_candidate_ids": [200],
            "source_pp_id": None,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza por una grande"
        )

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "source_selection")
        self.assertEqual(
            result.resolved_data["source_candidate_ids"], [11, 12]
        )
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200]
        )
        set_pending.assert_called_once()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_ambiguous_destination_returns_pending_destination_selection(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200, 201],
            "source_pp_id": 11,
            "destination_pp_id": None,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza chica por grande"
        )

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "destination_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11])
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200, 201]
        )


class ProcessInitialModificarProductoRejectedTest(unittest.TestCase):
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_invalid_destination_quantity_returns_rejected(
        self, recognizer, set_pending
    ):
        """The orchestrator MUST reject an explicit invalid destination
        quantity BEFORE creating pending, resolving candidates or
        invoking the handler/service. This is the deterministic fix for
        the blocker `cambiar 2 ... por 0 ...`.
        """
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
            "cantidad_destino": None,
            "cantidad_destino_invalid": True,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiar 2 napolitanas por 0 muzza"
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data["reason"], "invalid_destination_quantity"
        )
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_no_source_candidates_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [],
            "destination_candidate_ids": [200],
            "source_pp_id": None,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_no_destination_candidates_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [],
            "source_pp_id": 11,
            "destination_pp_id": None,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_equivalent_source_destination_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [11],
            "source_pp_id": 11,
            "destination_pp_id": 11,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")


class ProcessInitialModificarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback(self):
        importlib.reload(initial_module)
        with open(initial_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "from backend.llm",
            "from backend.routers",
            "from backend.old_project",
            "build_modificar_producto_response",
            "from backend.intents.responses",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            initial_module.__all__,
            ["process_initial_modificar_producto"],
        )


if __name__ == "__main__":
    unittest.main()
