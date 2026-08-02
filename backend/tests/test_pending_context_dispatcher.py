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


if __name__ == "__main__":
    unittest.main()
