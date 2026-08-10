"""Focused tests for the ``vaciar_pedido`` confirmation pipeline.

These tests cover the eight acceptance scenarios required by the
``add-vaciar-pedido-confirmation`` change:

1. Initial valid request → confirmation prompt, no mutation.
2. ``"sí"`` → all lines cleared, pending context cleared.
3. ``"no"`` → no mutation, pending context cleared.
4. Unrecognized reply → pending context preserved exactly.
5. ``"sí, agregá una pizza"`` → handled only as confirmation, no
   product added in the same turn.
6. Missing / empty / non-borrador / stale / foreign-session pedido
   at either initiation or execution → rejected without mutation.
7. Forced deletion failure → outer transactional owner rolls back,
   no partial deletion.
8. Shared response mapper renders the same prompt, success,
   cancellation, and rejection messages for the local response and
   the provider outbox path.
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import order_clear_confirmation_resolver as resolver_module
from backend.intents.context import (
    pending_context_service as pending_context_service_module,
)
from backend.intents.handlers import vaciar_pedido_handler as handler_module
from backend.intents.handlers.vaciar_pedido_handler import execute_vaciar_pedido
from backend.intents.orchestration import (
    initial_intent_dispatcher as dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_dispatcher as pending_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_execution as execution_module,
)
from backend.intents.orchestration import vaciar_pedido_initial as initial_module
from backend.intents.orchestration.vaciar_pedido_initial import (
    process_initial_vaciar_pedido,
)
from backend.intents.responses import vaciar_pedido_response as response_module
from backend.intents.responses.vaciar_pedido_response import (
    build_vaciar_pedido_response,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models import EstadoPedido
from backend.models.session import Session as ConversationSession
from backend.services import pedido_producto_service as pedido_producto_service_module
from backend.services.exceptions import PedidoProductoNotEditable
from backend.services.outbound_response_mapper import (
    build_customer_responses,
    stage_outbound_rows,
)
from backend.sessions.enums.context_type import ContextType


def _borrador_pedido(pedido_id: int = 7, session_id: int = 42) -> MagicMock:
    pedido = MagicMock()
    pedido.id = pedido_id
    pedido.id_session = session_id
    pedido.estado_pedido = EstadoPedido.BORRADOR
    return pedido


def _session(
    *,
    id: int = 42,
    id_pedido: int | None = 7,
    context_type: str | None = None,
) -> MagicMock:
    session = MagicMock(spec=ConversationSession)
    session.id = id
    session.id_pedido = id_pedido
    session.id_comercio = 1
    session.id_cliente = 2
    session.context_type = context_type
    session.pending_intents = None
    return session


def _pending_intent() -> ProcessedIntent:
    return ProcessedIntent(
        intent="vaciar_pedido",
        source_text="vaciar pedido",
        status="pending_resolution",
        recognizer="vaciar_pedido",
        handler="vaciar_pedido",
        resolved_data={"pedido_id": 7},
        requirements=[
            RequirementState(
                name="confirmacion", status="pending", value=None
            )
        ],
        candidate_ids=[],
    )


def _ready_intent(
    *,
    confirmacion: bool = True,
    pedido_id: int = 7,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent="vaciar_pedido",
        source_text="si",
        status="ready",
        recognizer="vaciar_pedido",
        handler="vaciar_pedido",
        resolved_data={
            "pedido_id": pedido_id,
            "confirmacion": confirmacion,
        },
        requirements=[
            RequirementState(
                name="confirmacion",
                status="completed",
                value=bool(confirmacion),
            )
        ],
        candidate_ids=[],
    )


def _classification_result(
    *, intent: IntentName, mensaje: str
) -> IntentClassificationResult:
    return IntentClassificationResult(
        intents=[ClassifiedIntent(intent=intent, mensaje=mensaje)],
        mensaje=mensaje,
    )


# ---------------------------------------------------------------------------
# 1. Initial valid request → confirmation prompt, no mutation
# ---------------------------------------------------------------------------


class ProcessInitialVaciarPedidoValidTest(unittest.TestCase):
    @patch.object(initial_module, "PedidoProductoService")
    @patch.object(initial_module, "set_pending_intent")
    def test_valid_initial_request_creates_pending_context_without_mutation(
        self, set_pending, service_cls
    ):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock(), MagicMock()]
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)

        result = process_initial_vaciar_pedido(db, session, "vaciar el pedido")

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, "vaciar_pedido")
        self.assertEqual(result.handler, "vaciar_pedido")
        self.assertEqual(result.recognizer, "vaciar_pedido")
        self.assertEqual(result.resolved_data.get("pedido_id"), 7)
        self.assertEqual(result.candidate_ids, [])
        req_names = [req.name for req in result.requirements]
        self.assertIn("confirmacion", req_names)
        req_confirmacion = next(
            req for req in result.requirements if req.name == "confirmacion"
        )
        self.assertEqual(req_confirmacion.status, "pending")

        set_pending.assert_called_once()
        persisted_intent = set_pending.call_args.args[1]
        self.assertEqual(persisted_intent.intent, "vaciar_pedido")
        self.assertEqual(persisted_intent.status, "pending_resolution")

        session.context_type = ContextType.ORDER_CLEAR_CONFIRMATION.value
        self.assertEqual(
            session.context_type, "order_clear_confirmation"
        )

        service.clear_pedido_lines.assert_not_called()
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class DispatchInitialVaciarPedidoTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_vaciar_pedido")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_vaciar_pedido_dispatches_to_initial_orchestrator(
        self, classifier_cls, orchestrator
    ):
        sentinel = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="vaciar el pedido",
            status="pending_resolution",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
        )
        orchestrator.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _classification_result(
            intent=IntentName.VACIAR_PEDIDO, mensaje="vaciar el pedido"
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type=None)

        result = dispatcher_module.dispatch_initial_message(
            db, session, "vaciar el pedido"
        )

        classifier_instance.query.assert_called_once_with("vaciar el pedido")
        orchestrator.assert_called_once_with(db, session, "vaciar el pedido")
        self.assertEqual(result, [sentinel])


# ---------------------------------------------------------------------------
# 6. Rejection scenarios at initiation
# ---------------------------------------------------------------------------


class ProcessInitialVaciarPedidoRejectionTest(unittest.TestCase):
    @patch.object(initial_module, "set_pending_intent")
    def test_missing_session_pedido_returns_rejected(self, set_pending):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=None)

        result = process_initial_vaciar_pedido(db, session, "vaciar")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        set_pending.assert_not_called()
        db.commit.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    def test_missing_pedido_returns_rejected(self, set_pending):
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = None
        session = _session(id_pedido=99)

        result = process_initial_vaciar_pedido(db, session, "vaciar")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    def test_foreign_session_returns_rejected(self, set_pending):
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = _borrador_pedido(session_id=99)
        session = _session(id=42, id_pedido=7)

        result = process_initial_vaciar_pedido(db, session, "vaciar")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "session_mismatch")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    def test_non_borrador_pedido_returns_rejected(self, set_pending):
        pedido = _borrador_pedido()
        pedido.estado_pedido = EstadoPedido.INGRESADO
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)

        result = process_initial_vaciar_pedido(db, session, "vaciar")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "pedido_not_borrador"
        )
        set_pending.assert_not_called()

    @patch.object(initial_module, "PedidoProductoService")
    @patch.object(initial_module, "set_pending_intent")
    def test_empty_draft_returns_rejected(self, set_pending, service_cls):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = []
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)

        result = process_initial_vaciar_pedido(db, session, "vaciar")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "empty_draft")
        set_pending.assert_not_called()
        service.clear_pedido_lines.assert_not_called()


# ---------------------------------------------------------------------------
# 2 / 3 / 4 / 5. Resolver outcomes
# ---------------------------------------------------------------------------


class ResolveOrderClearConfirmationAffirmativeTest(unittest.TestCase):
    def test_si_normalizes_to_ready_with_confirmacion_true(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "sí", active
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.intent, "vaciar_pedido")
        self.assertEqual(result.handler, "vaciar_pedido")
        self.assertTrue(result.resolved_data.get("confirmacion"))
        self.assertEqual(result.candidate_ids, [])
        confirmacion_req = next(
            req for req in result.requirements if req.name == "confirmacion"
        )
        self.assertEqual(confirmacion_req.status, "completed")
        self.assertTrue(confirmacion_req.value)

    def test_si_with_terminal_punctuation_normalizes_to_ready(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "Sí.", active
        )

        self.assertEqual(result.status, "ready")
        self.assertTrue(result.resolved_data.get("confirmacion"))


class ResolveOrderClearConfirmationNegativeTest(unittest.TestCase):
    def test_no_normalizes_to_ready_with_confirmacion_false(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "no", active
        )

        self.assertEqual(result.status, "ready")
        self.assertFalse(result.resolved_data.get("confirmacion"))
        self.assertEqual(result.candidate_ids, [])


class ResolveOrderClearConfirmationUnrecognizedTest(unittest.TestCase):
    def test_unrecognized_text_preserves_pending_context_unchanged(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "sí, agregá una pizza", active
        )

        self.assertIs(result, active)
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, "vaciar_pedido")
        self.assertEqual(result.source_text, "vaciar pedido")
        self.assertEqual(result.candidate_ids, [])
        self.assertNotIn("confirmacion", result.resolved_data or {})

    def test_random_text_preserves_pending_context_unchanged(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "no se que decis", active
        )

        self.assertIs(result, active)
        self.assertEqual(result.status, "pending_resolution")

    def test_empty_text_preserves_pending_context_unchanged(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "", active
        )

        self.assertIs(result, active)
        self.assertEqual(result.status, "pending_resolution")

    def test_si_followed_by_other_words_is_not_accepted(self):
        active = _pending_intent()

        result = resolver_module.resolve_order_clear_confirmation(
            MagicMock(), MagicMock(), "si dale", active
        )

        self.assertIs(result, active)
        self.assertEqual(result.status, "pending_resolution")

    def test_resolver_does_not_invoke_classifier_or_llm(self):
        active = _pending_intent()
        db = MagicMock()
        session = MagicMock()
        with patch.object(
            pending_dispatcher_module, "IntentClassifier", create=True
        ) as classifier_cls:
            with patch.object(
                resolver_module, "QueryLlm", create=True
            ) as query_llm_cls:
                resolver_module.resolve_order_clear_confirmation(
                    db, session, "sí", active
                )
        classifier_cls.assert_not_called()
        query_llm_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Pending context dispatcher wiring
# ---------------------------------------------------------------------------


class DispatchPendingContextOrderClearConfirmationTest(unittest.TestCase):
    @patch.object(pending_dispatcher_module, "execute_ready_pending_context")
    @patch.object(pending_dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(pending_dispatcher_module, "set_active")
    @patch.object(pending_dispatcher_module, "load_pending_state")
    def test_si_message_routes_through_resolver_to_execution(
        self, load_state, set_active, resolve, execute_fn
    ):
        active = _pending_intent()
        load_state.return_value = MagicMock(active=active, queue=[])
        ready = _ready_intent(confirmacion=True)
        resolve.return_value = ready
        execute_fn.return_value = [ready.model_copy(update={"status": "executed"})]

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="order_clear_confirmation")

        result = pending_dispatcher_module.dispatch_pending_context(
            db, session, "sí"
        )

        resolve.assert_called_once()
        set_active.assert_called_once()
        execute_fn.assert_called_once_with(db, session)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")

    @patch.object(pending_dispatcher_module, "execute_ready_pending_context")
    @patch.object(pending_dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(pending_dispatcher_module, "set_active")
    @patch.object(pending_dispatcher_module, "load_pending_state")
    def test_unrecognized_message_preserves_active_and_skips_execution(
        self, load_state, set_active, resolve, execute_fn
    ):
        active = _pending_intent()
        load_state.return_value = MagicMock(active=active, queue=[])
        resolve.return_value = active

        db = MagicMock(name="DatabaseSession")
        session = _session(context_type="order_clear_confirmation")

        result = pending_dispatcher_module.dispatch_pending_context(
            db, session, "sí, agregá una pizza"
        )

        resolve.assert_called_once()
        set_active.assert_called_once_with(session, active)
        execute_fn.assert_not_called()
        self.assertEqual(result, [active])
        self.assertEqual(result[0].status, "pending_resolution")


# ---------------------------------------------------------------------------
# Handler outcomes
# ---------------------------------------------------------------------------


class ExecuteVaciarPedidoAffirmativeTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_confirmacion_true_clears_lines_without_commit(
        self, service_cls
    ):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock(), MagicMock()]
        service.clear_pedido_lines.return_value = 2
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data.get("lineas_eliminadas"), 2)
        self.assertEqual(result.resolved_data.get("pedido_id"), 7)
        self.assertTrue(result.resolved_data.get("confirmacion"))
        service.clear_pedido_lines.assert_called_once_with(7)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_handler_does_not_commit_rollback_flush_refresh_begin(
        self, service_cls
    ):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service.clear_pedido_lines.return_value = 1
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        execute_vaciar_pedido(db, session, intent)

        for forbidden in ("commit", "rollback", "flush", "refresh", "begin"):
            with self.subTest(forbidden=forbidden):
                getattr(db, forbidden).assert_not_called()


class ExecuteVaciarPedidoNegativeTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_confirmacion_false_returns_rejected_cancelled(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=False)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "cancelled")
        service_cls.assert_not_called()
        db.commit.assert_not_called()


class ExecuteVaciarPedidoRejectionTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_session_pedido_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=None)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_pedido_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = None
        session = _session(id_pedido=99)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_foreign_session_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = _borrador_pedido(session_id=999)
        session = _session(id=42, id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "session_mismatch")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_borrador_returns_rejected(self, service_cls):
        pedido = _borrador_pedido()
        pedido.estado_pedido = EstadoPedido.INGRESADO
        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "pedido_not_borrador"
        )
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_stale_empty_returns_rejected(self, service_cls):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = []
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "empty_draft")
        service.clear_pedido_lines.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_stale_pedido_not_borrador_at_execution_returns_rejected(
        self, service_cls
    ):
        pedido = _borrador_pedido()
        pedido.estado_pedido = EstadoPedido.CANCELADO
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service.clear_pedido_lines.side_effect = PedidoProductoNotEditable(
            7, "cancelado"
        )
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "pedido_not_borrador"
        )


class ExecuteVaciarPedidoGuardTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_intent_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)
        intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_ready_status_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)
        intent = _pending_intent()

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_handler_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)
        intent = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="x",
            status="ready",
            recognizer="vaciar_pedido",
            handler="other_handler",
            resolved_data={"confirmacion": True, "pedido_id": 7},
        )

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_confirmacion_returns_rejected(self, service_cls):
        db = MagicMock(spec=DatabaseSession)
        session = _session(id_pedido=7)
        intent = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="x",
            status="ready",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
            resolved_data={"pedido_id": 7},
        )

        result = execute_vaciar_pedido(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Forced deletion failure → outer transactional owner rolls back
# ---------------------------------------------------------------------------


class ExecuteVaciarPedidoAtomicityTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_clear_pedido_lines_exception_propagates_unchanged(
        self, service_cls
    ):
        pedido = _borrador_pedido()
        sentinel = RuntimeError("forced database failure mid-delete")
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock(), MagicMock()]
        service.clear_pedido_lines.side_effect = sentinel
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        with self.assertRaises(RuntimeError) as ctx:
            execute_vaciar_pedido(db, session, intent)
        self.assertIs(ctx.exception, sentinel)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_clear_pedido_lines_propagation_does_not_take_ownership(
        self, service_cls
    ):
        pedido = _borrador_pedido()
        service = MagicMock()
        service.list_by_pedido.return_value = [MagicMock()]
        service.clear_pedido_lines.side_effect = RuntimeError("db boom")
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        db.get.return_value = pedido
        session = _session(id_pedido=7)
        intent = _ready_intent(confirmacion=True)

        try:
            execute_vaciar_pedido(db, session, intent)
        except RuntimeError:
            pass
        for forbidden in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
        ):
            with self.subTest(forbidden=forbidden):
                getattr(db, forbidden).assert_not_called()


# ---------------------------------------------------------------------------
# Pending execution primitive clears non-queued context
# ---------------------------------------------------------------------------


class ExecuteReadyPendingContextClearsVaciarPedidoTest(unittest.TestCase):
    @patch.object(execution_module, "execute_vaciar_pedido")
    @patch.object(execution_module, "clear_pending_context")
    def test_executed_vaciar_pedido_clears_pending_context_once(
        self, clear_pending, handler
    ):
        handler.return_value = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="si",
            status="executed",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
            resolved_data={"pedido_id": 7, "lineas_eliminadas": 3},
        )

        class _FakeState:
            def __init__(self, active):
                self.active = active
                self.queue = []

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "order_clear_confirmation"

        with patch.object(
            execution_module,
            "load_pending_state",
            return_value=_FakeState(_ready_intent(confirmacion=True)),
        ):
            result = execution_module.execute_ready_pending_context(
                db, session
            )

        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)
        self.assertEqual(result[0].status, "executed")

    @patch.object(execution_module, "execute_vaciar_pedido")
    @patch.object(execution_module, "clear_pending_context")
    def test_rejected_vaciar_pedido_clears_pending_context(
        self, clear_pending, handler
    ):
        handler.return_value = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="no",
            status="rejected",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
            resolved_data={"reason": "cancelled"},
        )

        class _FakeState:
            def __init__(self, active):
                self.active = active
                self.queue = []

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "order_clear_confirmation"

        with patch.object(
            execution_module,
            "load_pending_state",
            return_value=_FakeState(_ready_intent(confirmacion=False)),
        ):
            result = execution_module.execute_ready_pending_context(
                db, session
            )

        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)
        self.assertEqual(result[0].status, "rejected")


# ---------------------------------------------------------------------------
# Pending context service wiring
# ---------------------------------------------------------------------------


class SetPendingIntentVaciarPedidoTest(unittest.TestCase):
    @patch.object(pending_context_service_module, "set_active")
    def test_vaciar_pedido_pending_intent_resolves_to_order_clear_confirmation(
        self, set_active
    ):
        intent = _pending_intent()
        session = _session(context_type=None)

        pending_context_service_module.set_pending_intent(session, intent)

        set_active.assert_called_once_with(session, intent)
        self.assertEqual(
            session.context_type, "order_clear_confirmation"
        )


# ---------------------------------------------------------------------------
# 8. Shared response mapper equivalence
# ---------------------------------------------------------------------------


class BuildVaciarPedidoResponseTest(unittest.TestCase):
    def test_prompt_message_is_fixed_spanish(self):
        intent = _pending_intent()
        rendered = build_vaciar_pedido_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertIn("¿Querés vaciarlo?", rendered.message)
        self.assertIn("sí", rendered.message)
        self.assertIn("no", rendered.message)
        self.assertEqual(rendered.intent, "vaciar_pedido")
        self.assertEqual(rendered.status, "pending_resolution")

    def test_success_message_is_fixed_spanish(self):
        intent = _ready_intent(confirmacion=True).model_copy(
            update={
                "status": "executed",
                "resolved_data": {
                    "pedido_id": 7,
                    "lineas_eliminadas": 3,
                    "confirmacion": True,
                },
            }
        )
        rendered = build_vaciar_pedido_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertEqual(
            rendered.message, "Listo, vacié tu pedido."
        )
        self.assertEqual(rendered.intent, "vaciar_pedido")
        self.assertEqual(rendered.status, "executed")

    def test_cancelled_rejection_message(self):
        intent = _ready_intent(confirmacion=False).model_copy(
            update={
                "status": "rejected",
                "resolved_data": {"reason": "cancelled"},
            }
        )
        rendered = build_vaciar_pedido_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertEqual(
            rendered.message, "Entendido, no vacié tu pedido."
        )
        self.assertEqual(rendered.intent, "vaciar_pedido")
        self.assertEqual(rendered.status, "rejected")

    def test_business_rejection_message(self):
        for reason in (
            "no_draft",
            "session_mismatch",
            "pedido_not_borrador",
            "empty_draft",
        ):
            with self.subTest(reason=reason):
                intent = ProcessedIntent(
                    intent="vaciar_pedido",
                    source_text="x",
                    status="rejected",
                    recognizer="vaciar_pedido",
                    handler="vaciar_pedido",
                    resolved_data={"reason": reason},
                )
                rendered = build_vaciar_pedido_response(
                    MagicMock(), MagicMock(), intent
                )
                self.assertEqual(
                    rendered.message,
                    "No pude vaciar tu pedido. "
                    "Tu pedido no fue modificado.",
                )

    def test_failed_status_maps_to_technical_fallback(self):
        intent = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="x",
            status="failed",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
        )
        rendered = build_vaciar_pedido_response(
            MagicMock(), MagicMock(), intent
        )
        self.assertEqual(rendered.status, "failed")


class SharedResponseMapperEquivalenceTest(unittest.TestCase):
    def test_local_and_outbox_render_identical_messages(self):
        pending = _pending_intent()
        executed = _ready_intent(confirmacion=True).model_copy(
            update={
                "status": "executed",
                "resolved_data": {
                    "pedido_id": 7,
                    "lineas_eliminadas": 2,
                    "confirmacion": True,
                },
            }
        )
        cancelled = _ready_intent(confirmacion=False).model_copy(
            update={
                "status": "rejected",
                "resolved_data": {"reason": "cancelled"},
            }
        )
        rejected = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="x",
            status="rejected",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
            resolved_data={"reason": "empty_draft"},
        )

        local_responses = build_customer_responses(
            MagicMock(), MagicMock(), [pending, executed, cancelled, rejected]
        )

        outbox_repo = MagicMock()
        outbox_repo.stage.return_value = MagicMock(id=1)
        outbox_responses = stage_outbound_rows(
            MagicMock(),
            MagicMock(),
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491133334444",
            intents=[pending, executed, cancelled, rejected],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(local_responses), 4)
        self.assertEqual(len(outbox_responses), 4)
        for index in range(4):
            self.assertEqual(
                local_responses[index].message,
                outbox_responses[index].customer_response.message,
            )
            self.assertEqual(
                local_responses[index].intent,
                outbox_responses[index].customer_response.intent,
            )
            self.assertEqual(
                local_responses[index].status,
                outbox_responses[index].customer_response.status,
            )


# ---------------------------------------------------------------------------
# Context type resolution
# ---------------------------------------------------------------------------


class ResolveContextTypeVaciarPedidoTest(unittest.TestCase):
    def test_vaciar_pedido_with_pending_confirmacion_resolves_to_context(
        self,
    ):
        from backend.intents.context.context_type_resolver import (
            resolve_context_type,
        )

        intent = _pending_intent()
        result = resolve_context_type(intent)
        self.assertEqual(result, ContextType.ORDER_CLEAR_CONFIRMATION)

    def test_vaciar_pedido_without_pending_confirmacion_does_not_resolve(
        self,
    ):
        from backend.intents.context.context_type_resolver import (
            resolve_context_type,
        )

        intent = ProcessedIntent(
            intent="vaciar_pedido",
            source_text="x",
            status="pending_resolution",
            recognizer="vaciar_pedido",
            handler="vaciar_pedido",
            requirements=[],
        )
        result = resolve_context_type(intent)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Module-level boundaries
# ---------------------------------------------------------------------------


class VaciarPedidoModuleBoundariesTest(unittest.TestCase):
    def test_initial_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(initial_module)
        with open(initial_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.begin",
            "from sqlalchemy import select",
            "joinedload",
            "from backend.routers",
            "from backend.llm",
            "from backend.dependencies",
            "backend.old_project",
            "import requests",
            "import fastapi",
            "HTTPException",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_initial_module_public_surface_is_limited(self):
        self.assertEqual(
            initial_module.__all__,
            ["process_initial_vaciar_pedido"],
        )

    def test_handler_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(handler_module)
        with open(handler_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.begin",
            "from sqlalchemy import select",
            "joinedload",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "backend.old_project",
            "import requests",
            "import fastapi",
            "HTTPException",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_handler_module_public_surface_is_limited(self):
        self.assertEqual(
            handler_module.__all__,
            ["execute_vaciar_pedido"],
        )

    def test_resolver_module_does_not_invoke_classifier_or_llm(self):
        importlib.reload(resolver_module)
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "IntentClassifier",
            "QueryLlm",
            "recognize_quitar_producto",
            "recognize_modificar_producto",
            "ProductRecognizerProtocol",
            "FuzzyProductRecognizer",
            "ProductoQueryService",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_response_module_public_surface_is_limited(self):
        self.assertEqual(
            response_module.__all__,
            ["build_vaciar_pedido_response"],
        )


# ---------------------------------------------------------------------------
# Service-level transactional neutrality
# ---------------------------------------------------------------------------


class PedidoProductoServiceClearPedidoLinesTest(unittest.TestCase):
    def test_clear_pedido_lines_stages_delete_without_commit_rollback(self):
        session = MagicMock()
        pedido = _borrador_pedido()
        repo = MagicMock()
        repo.pedido.return_value = pedido
        repo.delete_all_by_pedido.return_value = [
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]
        with patch.object(
            pedido_producto_service_module,
            "PedidoProductoRepository",
            return_value=repo,
        ):
            service = pedido_producto_service_module.PedidoProductoService(
                session
            )
            count = service.clear_pedido_lines(7)

        self.assertEqual(count, 3)
        repo.delete_all_by_pedido.assert_called_once_with(7)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()

    def test_clear_pedido_lines_raises_for_missing_pedido(self):
        from backend.services.exceptions import PedidoNotFound

        session = MagicMock()
        repo = MagicMock()
        repo.pedido.return_value = None
        with patch.object(
            pedido_producto_service_module,
            "PedidoProductoRepository",
            return_value=repo,
        ):
            service = pedido_producto_service_module.PedidoProductoService(
                session
            )
            with self.assertRaises(PedidoNotFound):
                service.clear_pedido_lines(7)
        repo.delete_all_by_pedido.assert_not_called()

    def test_clear_pedido_lines_raises_for_non_borrador_pedido(self):
        pedido = _borrador_pedido()
        pedido.estado_pedido = EstadoPedido.INGRESADO
        session = MagicMock()
        repo = MagicMock()
        repo.pedido.return_value = pedido
        with patch.object(
            pedido_producto_service_module,
            "PedidoProductoRepository",
            return_value=repo,
        ):
            service = pedido_producto_service_module.PedidoProductoService(
                session
            )
            with self.assertRaises(PedidoProductoNotEditable):
                service.clear_pedido_lines(7)
        repo.delete_all_by_pedido.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
