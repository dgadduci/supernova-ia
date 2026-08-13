import unittest
from unittest.mock import MagicMock, patch

from backend.intents.orchestration import (
    pending_context_dispatcher as dispatcher_module,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.observability.events import (
    COMPONENT_PENDING_CONTEXT,
    EVENT_PENDING_CONTEXT_TRANSITION,
)
from backend.sessions.enums.context_type import ContextType


def _pending_intent(
    *,
    intent_name: str = "agregar_producto",
    candidate_ids: list[int] | None = None,
    source_text: str = "x",
    handler: str | None = None,
    resolved_data: dict | None = None,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent_name,
        source_text=source_text,
        status="pending_resolution",
        recognizer="recognizer_productos",
        handler=handler or intent_name,
        resolved_data=resolved_data or {},
        requirements=[
            RequirementState(
                name="producto_presentacion_id",
                status="pending",
                value=None,
            )
        ],
        candidate_ids=candidate_ids or [101, 102],
    )


class _FakeState:
    def __init__(self, active=None, queue=None):
        self.active = active
        self.queue = queue or []


class DispatchPendingContextInitialBoundaryTest(unittest.TestCase):
    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_clarification_only_message_bypasses_initial_classifier(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent()
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = active
        resolver_cls.return_value = resolver
        exec_fn.return_value = [active]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "picante")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "pending_resolution")
        self.assertEqual(result[0].source_text, "x")

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_pending_clarification_returns_single_outcome_without_duplication(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102, 103])
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = active
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "no se cual")

        self.assertEqual(len(result), 1)
        exec_fn.assert_not_called()

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_clarification_only_message_does_not_invoke_initial_classifier(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        """`process_incoming_message` relies on `dispatch_pending_context`
        returning resolved outcomes without re-running the intent
        classifier; this test asserts the same at the dispatcher boundary.
        """
        active = _pending_intent()
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = active
        resolver_cls.return_value = resolver
        exec_fn.return_value = [active]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        with patch.object(
            dispatcher_module,
            "IntentClassifier",
            create=True,
        ) as classifier_cls:
            result = dispatch_pending_context(db, session, "la grande")

        self.assertEqual(len(result), 1)
        classifier_cls.assert_not_called()


class DispatchPendingContextOrderedPropagationTest(unittest.TestCase):
    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ordered_list_returned_unchanged_from_execution(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[42])
        resolved = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 42},
                "candidate_ids": [],
            }
        )
        executed = resolved.model_copy(update={"status": "executed"})
        promoted = _pending_intent(
            intent_name="agregar_producto",
            candidate_ids=[201, 202],
            source_text="promoted_y",
        )
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = resolved
        resolver_cls.return_value = resolver
        exec_fn.return_value = [executed, promoted]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "la grande")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "pending_resolution")
        self.assertEqual(result[1].source_text, "promoted_y")


class DispatchPendingContextActiveOnlyTest(unittest.TestCase):
    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_inactive_queued_clarification_is_not_returned(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(source_text="active_a")
        resolved = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 42},
                "candidate_ids": [],
            }
        )
        executed = resolved.model_copy(update={"status": "executed"})
        promoted = _pending_intent(source_text="active_b")
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = resolved
        resolver_cls.return_value = resolver
        exec_fn.return_value = [executed, promoted]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "la grande")

        self.assertEqual(len(result), 2)
        self.assertNotIn("inactive_queued_item", [r.source_text for r in result])
        exec_fn.assert_called_once()


class DispatchPendingContextStateOwnershipTest(unittest.TestCase):
    """3.1/3.2: dispatcher persists the resolver result once and ready
    execution receives that authoritative value. The pre-resolution
    active value or stale serialized pending state must never overwrite
    the newly ready active intent."""

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_resolver_result_persisted_exactly_once_before_ready_execution(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        resolved = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 11},
                "candidate_ids": [],
            }
        )
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = resolved
        resolver_cls.return_value = resolver

        captured: dict = {}

        def _capture(session, value):
            captured["persisted"] = value
            return _FakeState(active=value)

        set_active.side_effect = _capture
        exec_fn.return_value = [resolved.model_copy(update={"status": "executed"})]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "picante")

        self.assertEqual(set_active.call_count, 1)
        self.assertEqual(captured["persisted"].status, "ready")
        self.assertEqual(captured["persisted"].candidate_ids, [])
        self.assertEqual(
            captured["persisted"].resolved_data["producto_presentacion_id"], 11
        )
        exec_fn.assert_called_once_with(db, session)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_pre_resolution_active_is_not_passed_to_ready_execution(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        """3.1: the stale pending active must never leak into the
        ready execution invocation."""
        stale = _pending_intent(candidate_ids=[101, 102])
        ready = stale.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 11},
                "candidate_ids": [],
            }
        )
        load_state.return_value = _FakeState(active=stale)
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver
        exec_fn.return_value = [ready.model_copy(update={"status": "executed"})]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        dispatch_pending_context(db, session, "picante")

        exec_fn.assert_called_once_with(db, session)


class DispatchPendingContextAmbiguousRefinementTest(unittest.TestCase):
    """3.3: ambiguous refinement updates only active state, preserves
    FIFO queue contents, and never duplicates or reclassifies the
    active Carne intent."""

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ambiguous_refinement_persists_only_refined_active(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        queued_a = _pending_intent(
            source_text="queued_a", candidate_ids=[301, 302]
        )
        queued_b = _pending_intent(
            source_text="queued_b", candidate_ids=[401, 402]
        )
        active = _pending_intent(
            source_text="una empanada de carne", candidate_ids=[11, 12, 13],
        )
        refined = active.model_copy(update={"candidate_ids": [11, 12]})

        load_state.return_value = _FakeState(active=active, queue=[queued_a, queued_b])
        resolver = MagicMock()
        resolver.resolve.return_value = refined
        resolver_cls.return_value = resolver

        captured: list = []

        def _capture(session, value):
            captured.append(value)
            return _FakeState(active=value, queue=[queued_a, queued_b])

        set_active.side_effect = _capture

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "no se cual")

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].candidate_ids, [11, 12])
        self.assertEqual(captured[0].intent, "agregar_producto")
        self.assertEqual(captured[0].source_text, "una empanada de carne")
        exec_fn.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate_ids, [11, 12])
        self.assertEqual(result[0].status, "pending_resolution")
        self.assertEqual(result[0].intent, "agregar_producto")

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ambiguous_refinement_preserves_queue_in_order(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        queued_a = _pending_intent(
            source_text="queued_a", candidate_ids=[301, 302]
        )
        queued_b = _pending_intent(
            source_text="queued_b", candidate_ids=[401, 402]
        )
        active = _pending_intent(
            source_text="una empanada de carne", candidate_ids=[11, 12, 13],
        )
        refined = active.model_copy(update={"candidate_ids": [11]})

        load_state.return_value = _FakeState(active=active, queue=[queued_a, queued_b])
        resolver = MagicMock()
        resolver.resolve.return_value = refined
        resolver_cls.return_value = resolver

        captured_queue: list = []

        def _capture(session, value):
            captured_queue.append(value)
            return _FakeState(active=value, queue=[queued_a, queued_b])

        set_active.side_effect = _capture

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        dispatch_pending_context(db, session, "picante")

        self.assertEqual(len(captured_queue), 1)
        self.assertEqual(captured_queue[0].candidate_ids, [11])


class DispatchPendingContextRejectedCleanupTest(unittest.TestCase):
    """1.2 / 2.1: a resolver-produced `rejected` result clears the
    active pending state and `session.context_type` within the existing
    caller-owned transaction and returns the rejected outcome once."""

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_product_selection_rejected_clears_active_state_and_context(
        self, clear_pending, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        rejected = active.model_copy(update={"status": "rejected"})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = rejected
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "xyz")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        clear_pending.assert_called_once_with(session)
        set_active.assert_not_called()
        self.assertIsNone(session.context_type)
        exec_fn.assert_not_called()

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_rejected_does_not_persist_active_intent(
        self, clear_pending, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        rejected = active.model_copy(update={"status": "rejected"})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = rejected
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        dispatch_pending_context(db, session, "xyz")

        set_active.assert_not_called()
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_failed_resolution_does_not_clear_pending_state(
        self, clear_pending, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        failed = active.model_copy(update={"status": "failed"})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = failed
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "unknown")

        clear_pending.assert_not_called()
        set_active.assert_called_once_with(session, failed)
        self.assertEqual(
            session.context_type, ContextType.PRODUCT_SELECTION.value
        )
        exec_fn.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "failed")


class DispatchPendingContextStatusInterruptionTest(unittest.TestCase):
    """1.1: a closed deterministic status query interrupts the supported
    pending context read-only, preserving pending state exactly."""

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_explicit_status_query_with_product_selection_preserves_context(
        self, clear_pending, status_query, load_state, set_active,
        resolver_cls, exec_fn,
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        load_state.return_value = _FakeState(active=active)
        status_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="Cuál es el estado de mi pedido",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "preparacion"},
        )
        status_query.return_value = status_intent

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value
        session.id_pedido = 99

        result = dispatch_pending_context(db, session, "Cuál es el estado de mi pedido")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "consultar_estado_pedido")
        self.assertEqual(result[0].status, "executed")
        status_query.assert_called_once_with(db, session, "Cuál es el estado de mi pedido")
        resolver_cls.assert_not_called()
        set_active.assert_not_called()
        clear_pending.assert_not_called()
        self.assertEqual(
            session.context_type, ContextType.PRODUCT_SELECTION.value
        )
        exec_fn.assert_not_called()
        post_state = load_state.return_value
        self.assertEqual(post_state.active.candidate_ids, [101, 102])

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "resolve_order_line_selection")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_explicit_status_query_with_order_line_selection_preserves_context(
        self, clear_pending, status_query, resolve_line, load_state,
        set_active, exec_fn,
    ):
        active = _pending_intent(
            intent_name="quitar_producto",
            candidate_ids=[201, 202],
            handler="quitar_producto",
        )
        load_state.return_value = _FakeState(active=active)
        rejected_status = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado de mi pedido",
            status="rejected",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"reason": "no_pedido_asociado"},
        )
        status_query.return_value = rejected_status

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.ORDER_LINE_SELECTION.value
        session.id_pedido = None

        result = dispatch_pending_context(db, session, "estado de mi pedido")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        resolve_line.assert_not_called()
        set_active.assert_not_called()
        clear_pending.assert_not_called()
        self.assertEqual(
            session.context_type, ContextType.ORDER_LINE_SELECTION.value
        )
        exec_fn.assert_not_called()
        post_state = load_state.return_value
        self.assertEqual(post_state.active.candidate_ids, [201, 202])

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_ordinary_clarification_is_not_interrupted_by_status_predicate(
        self, clear_pending, status_query, load_state, set_active,
        resolver_cls, exec_fn,
    ):
        active = _pending_intent(candidate_ids=[301, 302])
        refined = active.model_copy(update={"candidate_ids": [301]})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = refined
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        result = dispatch_pending_context(db, session, "Grande")

        status_query.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate_ids, [301])
        self.assertEqual(result[0].status, "pending_resolution")
        clear_pending.assert_not_called()
        self.assertEqual(
            session.context_type, ContextType.PRODUCT_SELECTION.value
        )

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_status_query_after_rejection_uses_initial_dispatch_path(
        self, clear_pending, status_query, load_state, set_active,
        resolver_cls, exec_fn,
    ):
        """After a definitive rejection, ``session.context_type`` is
        ``None`` and ``load_pending_state`` returns no active intent, so
        the next call returns the empty-state rejected outcome without
        invoking the resolver or the status predicate."""
        active = _pending_intent(candidate_ids=[401])
        rejected = active.model_copy(update={"status": "rejected"})

        def _first_load(_session):
            return _FakeState(active=active)

        load_state.side_effect = [
            _FakeState(active=active),
            _FakeState(active=None),
            _FakeState(active=None),
            _FakeState(active=None),
        ]

        resolver = MagicMock()
        resolver.resolve.return_value = rejected
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        first = dispatch_pending_context(db, session, "xyz")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].status, "rejected")
        self.assertIsNone(session.context_type)
        status_query.assert_not_called()

        clear_pending.assert_called_once_with(session)
        status_query.reset_mock()
        second = dispatch_pending_context(db, session, "estado de mi pedido")
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].status, "rejected")
        status_query.assert_not_called()

    def test_no_transaction_control_methods_are_invoked_on_rejected(self):
        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value
        active = _pending_intent(candidate_ids=[501])
        rejected = active.model_copy(update={"status": "rejected"})

        with patch.object(
            dispatcher_module, "load_pending_state",
            return_value=_FakeState(active=active),
        ), patch.object(
            dispatcher_module, "set_active",
        ), patch.object(
            dispatcher_module, "ProductSelectionContextService",
        ) as resolver_cls, patch.object(
            dispatcher_module, "clear_pending_state", create=True,
        ), patch.object(
            dispatcher_module, "execute_ready_pending_context",
        ):
            resolver = MagicMock()
            resolver.resolve.return_value = rejected
            resolver_cls.return_value = resolver

            dispatch_pending_context(db, session, "xyz")

        for method in (
            "commit", "rollback", "begin", "flush", "refresh", "expire", "close",
        ):
            getattr(db, method).assert_not_called()


class DispatchPendingContextTransitionEmissionTest(unittest.TestCase):
    """2.1 / 2.2: the dispatcher emits privacy-safe closed
    ``pending_context_transition`` events for each business outcome."""

    def _capture_emit(self):
        captured: list[dict] = []

        def _fake_emit(**kwargs):
            captured.append(kwargs)
            return True

        return captured, _fake_emit

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_pending_preserved_event_emitted_with_candidate_counts(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[11, 12, 13])
        refined = active.model_copy(update={"candidate_ids": [11, 12]})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = refined
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured, fake_emit = self._capture_emit()
        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            dispatch_pending_context(db, session, "no se cual")

        self.assertEqual(len(captured), 1)
        kwargs = captured[0]
        self.assertEqual(kwargs["event"], EVENT_PENDING_CONTEXT_TRANSITION)
        self.assertEqual(kwargs["component"], COMPONENT_PENDING_CONTEXT)
        self.assertEqual(kwargs["outcome"], "pending_preserved")
        self.assertEqual(kwargs["context_kind"], "product_selection")
        self.assertEqual(kwargs["candidate_count_before"], 3)
        self.assertEqual(kwargs["candidate_count_after"], 2)
        self.assertFalse(kwargs["context_cleared"])

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    def test_rejected_cleared_event_emitted_with_context_cleared_true(
        self, clear_pending, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[21, 22])
        rejected = active.model_copy(update={"status": "rejected"})
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = rejected
        resolver_cls.return_value = resolver

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured, fake_emit = self._capture_emit()
        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            dispatch_pending_context(db, session, "xyz")

        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "rejected_cleared")
        self.assertTrue(kwargs["context_cleared"])
        self.assertEqual(kwargs["status_after"], "rejected")
        self.assertEqual(kwargs["candidate_count_before"], 2)
        self.assertEqual(kwargs["candidate_count_after"], 2)

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    def test_status_interrupted_event_emitted_with_no_context_change(
        self, status_query, load_state, set_active, resolver_cls, exec_fn,
    ):
        active = _pending_intent(candidate_ids=[31, 32])
        load_state.return_value = _FakeState(active=active)
        status_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="cuál es el estado de mi pedido",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "preparacion"},
        )
        status_query.return_value = status_intent

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured, fake_emit = self._capture_emit()
        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            dispatch_pending_context(
                db, session, "cuál es el estado de mi pedido"
            )

        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "status_interrupted")
        self.assertFalse(kwargs["context_cleared"])
        self.assertEqual(kwargs["candidate_count_before"], 2)
        self.assertEqual(kwargs["candidate_count_after"], 2)
        self.assertEqual(kwargs["status_after"], "executed")

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_emit_event_failure_leaves_business_outcome_unchanged(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[41, 42])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 41},
                "candidate_ids": [],
            }
        )
        load_state.return_value = _FakeState(active=active)
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver
        executed = ready.model_copy(update={"status": "executed"})
        exec_fn.return_value = [executed]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        def _exploding_emit(**kwargs):
            raise RuntimeError("observability sink boom")

        with patch.object(dispatcher_module, "emit_event", side_effect=_exploding_emit):
            result = dispatch_pending_context(db, session, "grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        exec_fn.assert_called_once()


class DispatchPendingContextPostExecutionTraceTest(unittest.TestCase):
    """The trace emitted after ``execute_ready_pending_context`` must
    reflect the actual executed outcome and the effective persisted
    session/pending state, never an invented ``status_after=ready`` /
    ``context_cleared=False`` triple for a ready-execution branch."""

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ready_executed_records_executed_and_context_cleared(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[71, 72])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 71},
                "candidate_ids": [],
            }
        )
        executed_intent = ready.model_copy(update={"status": "executed"})
        load_state.side_effect = [
            _FakeState(active=active),
            _FakeState(active=ready),
            _FakeState(active=None),
        ]
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver

        def _post_execute_clear(db, session):
            session.context_type = None
            return [executed_intent]

        exec_fn.side_effect = _post_execute_clear

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with patch.object(dispatcher_module, "emit_event", side_effect=_capture):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(len(captured), 1)
        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "ready_executed")
        self.assertEqual(kwargs["status_before"], "pending_resolution")
        self.assertEqual(kwargs["status_after"], "executed")
        self.assertTrue(kwargs["context_cleared"])
        self.assertEqual(kwargs["candidate_count_before"], 2)
        self.assertEqual(kwargs["candidate_count_after"], 0)
        self.assertIsNone(session.context_type)
        exec_fn.assert_called_once()

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ready_executed_promoting_pending_records_pending_preserved(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        queued = _pending_intent(candidate_ids=[201, 202], source_text="queued")
        active = _pending_intent(candidate_ids=[71, 72])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 71},
                "candidate_ids": [],
            }
        )
        executed_intent = ready.model_copy(update={"status": "executed"})

        class _State:
            def __init__(self, active, queue=None):
                self.active = active
                self.queue = queue or []

        load_state.side_effect = [
            _State(active=active, queue=[queued]),
            _State(active=ready, queue=[queued]),
            _State(active=queued, queue=[]),
        ]
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver

        def _promote(db, session):
            return [executed_intent, queued.model_copy()]

        exec_fn.side_effect = _promote

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with patch.object(dispatcher_module, "emit_event", side_effect=_capture):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(result[1].status, "pending_resolution")
        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "pending_preserved")
        self.assertEqual(kwargs["status_after"], "pending_resolution")
        self.assertFalse(kwargs["context_cleared"])
        self.assertEqual(kwargs["candidate_count_after"], 2)
        self.assertEqual(
            session.context_type, ContextType.PRODUCT_SELECTION.value
        )

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ready_execution_rejected_records_rejected_cleared(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[81, 82])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 81},
                "candidate_ids": [],
            }
        )
        rejected_intent = ready.model_copy(update={"status": "rejected"})
        load_state.side_effect = [
            _FakeState(active=active),
            _FakeState(active=ready),
            _FakeState(active=None),
        ]
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver

        def _rejected_execute(db, session):
            session.context_type = None
            return [rejected_intent]

        exec_fn.side_effect = _rejected_execute

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with patch.object(dispatcher_module, "emit_event", side_effect=_capture):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "rejected_cleared")
        self.assertEqual(kwargs["status_after"], "rejected")
        self.assertTrue(kwargs["context_cleared"])
        self.assertIsNone(session.context_type)

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ready_execution_failed_records_pending_preserved(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[91, 92])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 91},
                "candidate_ids": [],
            }
        )
        failed_intent = ready.model_copy(update={"status": "failed"})
        load_state.side_effect = [
            _FakeState(active=active),
            _FakeState(active=ready),
            _FakeState(active=ready),
        ]
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver
        exec_fn.return_value = [failed_intent]

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with patch.object(dispatcher_module, "emit_event", side_effect=_capture):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "failed")
        kwargs = captured[0]
        self.assertEqual(kwargs["outcome"], "pending_preserved")
        self.assertEqual(kwargs["status_after"], "failed")
        self.assertFalse(kwargs["context_cleared"])
        self.assertEqual(
            session.context_type, ContextType.PRODUCT_SELECTION.value
        )

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "load_pending_state")
    def test_ready_execution_emit_failure_preserves_business_outcome(
        self, load_state, set_active, resolver_cls, exec_fn
    ):
        active = _pending_intent(candidate_ids=[101, 102])
        ready = active.model_copy(
            update={
                "status": "ready",
                "resolved_data": {"producto_presentacion_id": 101},
                "candidate_ids": [],
            }
        )
        executed_intent = ready.model_copy(update={"status": "executed"})
        load_state.side_effect = [
            _FakeState(active=active),
            _FakeState(active=ready),
            _FakeState(active=None),
        ]
        resolver = MagicMock()
        resolver.resolve.return_value = ready
        resolver_cls.return_value = resolver

        def _executed_clear(db, session):
            session.context_type = None
            return [executed_intent]

        exec_fn.side_effect = _executed_clear

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        def _exploding_emit(**kwargs):
            raise RuntimeError("observability sink boom")

        with patch.object(dispatcher_module, "emit_event", side_effect=_exploding_emit):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        self.assertIsNone(session.context_type)
        exec_fn.assert_called_once()


class DispatchPendingContextInvalidStateRecoveryTest(unittest.TestCase):
    """5.1 / 5.2 / 5.3: the dispatcher recognises three inconsistent
    pending-state shapes and recovers them without invoking the
    classifier, resolver, LLM, product handler, catalog or
    transaction-control methods.

    For each shape it MUST:

    * return exactly one ``rejected`` outcome;
    * clear the pending state and set ``session.context_type`` to
      ``None``;
    * emit a single closed ``pending_context_transition`` event with
      ``outcome=invalid_state_cleared`` and ``context_cleared=true``;
    * let the next ordinary message reach initial dispatch.
    """

    _FORBIDDEN_DURING_RECOVERY = (
        "IntentClassifier",
        "ProductSelectionContextService",
        "resolve_order_line_selection",
        "resolve_product_modification",
        "resolve_order_clear_confirmation",
        "execute_ready_pending_context",
        "process_initial_order_status_query",
        "execute_agregar_producto",
        "execute_modificar_producto",
        "execute_quitar_producto",
        "execute_set_observacion_producto",
        "execute_vaciar_pedido",
    )

    def _capture_emit(self):
        captured: list[dict] = []

        def _fake_emit(**kwargs):
            captured.append(kwargs)
            return True

        return captured, _fake_emit

    def _assert_no_forbidden_calls(self, mocks: dict) -> None:
        for name in self._FORBIDDEN_DURING_RECOVERY:
            self.assertFalse(
                mocks[name].called,
                f"forbidden call {name!r} invoked during recovery",
            )

    def _assert_no_transaction_control(self, db) -> None:
        for method in (
            "commit",
            "rollback",
            "begin",
            "flush",
            "refresh",
            "expire",
            "close",
        ):
            self.assertFalse(
                getattr(db, method).called,
                f"forbidden db.{method}() invoked during recovery",
            )

    def _assert_invalid_state_cleared_event(
        self,
        captured: list[dict],
        *,
        expected_context_kind: str,
        expected_candidate_count_before: int,
        expected_status_before: str,
    ) -> dict:
        invalid_events = [
            kwargs for kwargs in captured
            if kwargs.get("outcome") == "invalid_state_cleared"
        ]
        self.assertEqual(
            len(invalid_events),
            1,
            f"expected exactly one invalid_state_cleared event; "
            f"got {len(invalid_events)}: {captured}",
        )
        event = invalid_events[0]
        self.assertEqual(event["event"], EVENT_PENDING_CONTEXT_TRANSITION)
        self.assertEqual(event["component"], COMPONENT_PENDING_CONTEXT)
        self.assertTrue(event["context_cleared"])
        self.assertEqual(
            event["candidate_count_before"], expected_candidate_count_before
        )
        self.assertEqual(event["candidate_count_after"], 0)
        self.assertEqual(event["status_after"], "rejected")
        self.assertEqual(event["context_kind"], expected_context_kind)
        self.assertEqual(event["status_before"], expected_status_before)
        return event

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(dispatcher_module, "resolve_product_modification")
    @patch.object(dispatcher_module, "resolve_order_line_selection")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    @patch.object(dispatcher_module, "load_pending_state")
    def test_no_active_with_non_null_context_type_clears_state_and_emits_event(
        self, load_state, clear_pending, set_active, status_query,
        resolve_line, resolve_mod, resolve_clear, resolver_cls, exec_fn,
    ):
        """``active is None`` with a non-null supported context type
        MUST surface the actual supported kind (``product_selection``)
        so the operator can still tell which flow was being cleared,
        and the persisted ``status_before`` is the closed ``none``
        sentinel because no active intent was loaded."""
        load_state.return_value = _FakeState(active=None)
        captured, fake_emit = self._capture_emit()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = ContextType.PRODUCT_SELECTION.value

        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)
        set_active.assert_not_called()
        exec_fn.assert_not_called()
        status_query.assert_not_called()
        resolver_cls.assert_not_called()
        self._assert_invalid_state_cleared_event(
            captured,
            expected_context_kind=ContextType.PRODUCT_SELECTION.value,
            expected_candidate_count_before=0,
            expected_status_before="none",
        )
        self._assert_no_transaction_control(db)
        self._assert_no_forbidden_calls({
            "IntentClassifier": MagicMock(),
            "ProductSelectionContextService": resolver_cls,
            "resolve_order_line_selection": resolve_line,
            "resolve_product_modification": resolve_mod,
            "resolve_order_clear_confirmation": resolve_clear,
            "execute_ready_pending_context": exec_fn,
            "process_initial_order_status_query": status_query,
            "execute_agregar_producto": MagicMock(),
            "execute_modificar_producto": MagicMock(),
            "execute_quitar_producto": MagicMock(),
            "execute_set_observacion_producto": MagicMock(),
            "execute_vaciar_pedido": MagicMock(),
        })

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(dispatcher_module, "resolve_product_modification")
    @patch.object(dispatcher_module, "resolve_order_line_selection")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    @patch.object(dispatcher_module, "load_pending_state")
    def test_active_with_null_context_type_clears_state_and_emits_event(
        self, load_state, clear_pending, set_active, status_query,
        resolve_line, resolve_mod, resolve_clear, resolver_cls, exec_fn,
    ):
        """``active`` present with ``context_type is None`` MUST surface
        the closed ``none`` sentinel and report the real
        ``candidate_count_before`` from the loaded active intent so the
        operator can tell a candidate set was discarded versus an empty
        pending state."""
        active = _pending_intent(candidate_ids=[501, 502])
        load_state.return_value = _FakeState(active=active)
        captured, fake_emit = self._capture_emit()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = None

        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)
        set_active.assert_not_called()
        exec_fn.assert_not_called()
        status_query.assert_not_called()
        resolver_cls.assert_not_called()
        self._assert_invalid_state_cleared_event(
            captured,
            expected_context_kind="none",
            expected_candidate_count_before=2,
            expected_status_before="pending_resolution",
        )
        self._assert_no_transaction_control(db)

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(dispatcher_module, "resolve_product_modification")
    @patch.object(dispatcher_module, "resolve_order_line_selection")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    @patch.object(dispatcher_module, "load_pending_state")
    def test_active_with_unsupported_context_type_clears_state_and_emits_event(
        self, load_state, clear_pending, set_active, status_query,
        resolve_line, resolve_mod, resolve_clear, resolver_cls, exec_fn,
    ):
        """``active`` present with a non-null, non-supported
        ``context_type`` MUST surface the closed ``unsupported`` sentinel
        and report the real ``candidate_count_before``."""
        active = _pending_intent(candidate_ids=[601, 602])
        load_state.return_value = _FakeState(active=active)
        captured, fake_emit = self._capture_emit()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "future_context_kind"

        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            result = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        clear_pending.assert_called_once_with(session)
        self.assertIsNone(session.context_type)
        set_active.assert_not_called()
        exec_fn.assert_not_called()
        status_query.assert_not_called()
        resolver_cls.assert_not_called()
        self._assert_invalid_state_cleared_event(
            captured,
            expected_context_kind="unsupported",
            expected_candidate_count_before=2,
            expected_status_before="pending_resolution",
        )
        self._assert_no_transaction_control(db)

    @patch.object(dispatcher_module, "execute_ready_pending_context")
    @patch.object(dispatcher_module, "ProductSelectionContextService")
    @patch.object(dispatcher_module, "resolve_order_clear_confirmation")
    @patch.object(dispatcher_module, "resolve_product_modification")
    @patch.object(dispatcher_module, "resolve_order_line_selection")
    @patch.object(dispatcher_module, "process_initial_order_status_query")
    @patch.object(dispatcher_module, "set_active")
    @patch.object(dispatcher_module, "clear_pending_state", create=True)
    @patch.object(dispatcher_module, "load_pending_state")
    def test_recovery_then_process_incoming_message_reaches_initial_dispatch(
        self, load_state, clear_pending, set_active, status_query,
        resolve_line, resolve_mod, resolve_clear, resolver_cls, exec_fn,
    ):
        """5.4: the second turn MUST really reach initial dispatch.

        Turn 1 drives ``dispatch_pending_context`` from an inconsistent
        state (active present, ``context_type`` is unsupported). The
        recovery clears pending JSON, sets ``session.context_type``
        back to ``None`` and emits exactly one closed
        ``invalid_state_cleared`` event.

        Turn 2 calls ``process_incoming_message`` - the same entry point
        used by the provider coordinator - with a fresh message. The
        second message MUST reach the initial dispatcher (proven by
        ``IntentClassifier`` being instantiated and queried) and MUST
        NOT touch any pending resolver, status interruption, ready
        execution or product handler.
        """
        from backend.intents.orchestration import (
            initial_intent_dispatcher as initial_module,
        )
        from backend.intents.orchestration.incoming_message_orchestrator import (
            process_incoming_message,
        )
        from backend.intents.schemas.intent_classification import (
            ClassifiedIntent,
            IntentClassificationResult,
            IntentName,
        )

        active = _pending_intent(candidate_ids=[801, 802, 803])
        load_state.return_value = _FakeState(active=active)
        captured, fake_emit = self._capture_emit()

        db = MagicMock(name="DatabaseSession")
        session = MagicMock()
        session.context_type = "future_context_kind"

        with patch.object(dispatcher_module, "emit_event", side_effect=fake_emit):
            first = dispatch_pending_context(db, session, "Grande")

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].status, "rejected")
        self.assertIsNone(session.context_type)
        clear_pending.assert_called_once_with(session)
        self._assert_invalid_state_cleared_event(
            captured,
            expected_context_kind="unsupported",
            expected_candidate_count_before=3,
            expected_status_before="pending_resolution",
        )

        clear_pending.reset_mock()
        set_active.reset_mock()
        exec_fn.reset_mock()
        status_query.reset_mock()
        resolve_line.reset_mock()
        resolve_mod.reset_mock()
        resolve_clear.reset_mock()
        resolver_cls.reset_mock()

        classifier_constructor_calls: list = []
        classifier_query_calls: list = []

        class _ClassifierProbe:
            def __init__(self, *args, **kwargs):
                classifier_constructor_calls.append((args, kwargs))

            def query(self, message):
                classifier_query_calls.append(message)
                return IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONSULTAR_ESTADO_PEDIDO,
                            mensaje=message,
                        )
                    ],
                    mensaje=message,
                )

        with patch.object(
            initial_module, "IntentClassifier", _ClassifierProbe
        ), patch.object(
            dispatcher_module, "ProductSelectionContextService"
        ) as second_resolver_cls, patch.object(
            dispatcher_module, "resolve_order_line_selection"
        ) as second_resolve_line, patch.object(
            dispatcher_module, "resolve_product_modification"
        ) as second_resolve_mod, patch.object(
            dispatcher_module, "resolve_order_clear_confirmation"
        ) as second_resolve_clear, patch.object(
            dispatcher_module, "execute_ready_pending_context"
        ) as second_exec_fn, patch.object(
            dispatcher_module, "process_initial_order_status_query"
        ) as second_status_query, patch.object(
            dispatcher_module, "emit_event"
        ):
            second = process_incoming_message(
                db, session, "Cuál es el estado de mi pedido"
            )

        self.assertEqual(len(classifier_constructor_calls), 1)
        self.assertEqual(
            classifier_query_calls, ["Cuál es el estado de mi pedido"]
        )
        second_resolver_cls.assert_not_called()
        second_resolve_line.assert_not_called()
        second_resolve_mod.assert_not_called()
        second_resolve_clear.assert_not_called()
        second_exec_fn.assert_not_called()
        second_status_query.assert_not_called()
        self.assertGreaterEqual(len(second), 1)
        self.assertEqual(second[0].intent, "consultar_estado_pedido")
        for method in (
            "commit",
            "rollback",
            "begin",
            "flush",
            "refresh",
            "expire",
            "close",
        ):
            self.assertFalse(getattr(db, method).called)


if __name__ == "__main__":
    unittest.main()
