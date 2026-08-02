import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import (
    product_modification_resolver as resolver_module,
)
from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.orchestration import (
    initial_intent_dispatcher as initial_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_dispatcher as pending_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_execution as pending_execution_module,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession
from backend.sessions.enums.context_type import ContextType


def _ready_modificar_intent() -> ProcessedIntent:
    return ProcessedIntent(
        intent="modificar_producto",
        source_text="x",
        status="ready",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        resolved_data={
            "pedido_producto_origen_id": 1,
            "producto_presentacion_destino_id": 2,
        },
        requirements=[],
        candidate_ids=[],
    )


def _pending_modificar_intent(stage: str = "source_selection") -> ProcessedIntent:
    return ProcessedIntent(
        intent="modificar_producto",
        source_text="x",
        status="pending_resolution",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        stage=stage,  # type: ignore[arg-type]
        resolved_data={
            "source_candidate_ids": [1, 2],
            "destination_candidate_ids": [200],
        },
        requirements=[],
        candidate_ids=[],
    )


class InitialIntentDispatcherModificarProductoTest(unittest.TestCase):
    def test_dispatches_modificar_producto_intent(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.context_type = None

        class _StubClassifier:
            def query(self, message):
                return IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.MODIFICAR_PRODUCTO,
                            mensaje=message,
                        )
                    ],
                    mensaje=message,
                )

        with patch.object(
            initial_dispatcher_module, "IntentClassifier", _StubClassifier
        ):
            with patch.object(
                initial_dispatcher_module,
                "process_initial_modificar_producto",
            ) as proc:
                proc.return_value = ProcessedIntent(
                    intent="modificar_producto",
                    source_text="x",
                    status="pending_resolution",
                    recognizer="modificar_producto_recognizer",
                    handler="modificar_producto",
                    resolved_data={},
                    requirements=[],
                    candidate_ids=[],
                )
                result = dispatch_initial_message(db, session, "cambiá algo")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "modificar_producto")
        proc.assert_called_once()

    def test_does_not_invoke_other_orchestrators(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.context_type = None

        class _StubClassifier:
            def query(self, message):
                return IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.MODIFICAR_PRODUCTO,
                            mensaje=message,
                        )
                    ],
                    mensaje=message,
                )

        with patch.object(
            initial_dispatcher_module, "IntentClassifier", _StubClassifier
        ):
            with patch.object(
                initial_dispatcher_module, "process_initial_modificar_producto"
            ) as mod_proc:
                with patch.object(
                    initial_dispatcher_module,
                    "process_initial_agregar_producto",
                ) as agr_proc:
                    with patch.object(
                        initial_dispatcher_module,
                        "process_initial_quitar_producto",
                    ) as quit_proc:
                        mod_proc.return_value = ProcessedIntent(
                            intent="modificar_producto",
                            source_text="x",
                            status="ready",
                            recognizer="modificar_producto_recognizer",
                            handler="modificar_producto",
                            resolved_data={},
                            requirements=[],
                            candidate_ids=[],
                        )
                        dispatch_initial_message(db, session, "cambiá algo")

        mod_proc.assert_called_once()
        agr_proc.assert_not_called()
        quit_proc.assert_not_called()


class PendingContextDispatcherProductModificationTest(unittest.TestCase):
    def test_routes_product_modification_to_resolver(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.context_type = ContextType.PRODUCT_MODIFICATION.value

        state = MagicMock()
        state.active = _pending_modificar_intent()

        with patch.object(
            pending_dispatcher_module, "load_pending_state", return_value=state
        ):
            with patch.object(
                pending_dispatcher_module, "set_active"
            ) as set_active:
                with patch.object(
                    pending_dispatcher_module,
                    "resolve_product_modification",
                ) as resolve:
                    resolve.return_value = _pending_modificar_intent(
                        "destination_selection"
                    )
                    result = dispatch_pending_context(db, session, "x")

        resolve.assert_called_once()
        self.assertEqual(result[0].status, "pending_resolution")
        self.assertEqual(result[0].stage, "destination_selection")
        set_active.assert_called_once()

    def test_ready_product_modification_triggers_execution(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.context_type = ContextType.PRODUCT_MODIFICATION.value

        ready_intent = _ready_modificar_intent()
        state = MagicMock()
        state.active = _pending_modificar_intent()

        with patch.object(
            pending_dispatcher_module, "load_pending_state", return_value=state
        ):
            with patch.object(
                pending_dispatcher_module, "set_active"
            ) as set_active:
                with patch.object(
                    pending_dispatcher_module,
                    "resolve_product_modification",
                ) as resolve:
                    resolve.return_value = ready_intent
                    with patch.object(
                        pending_dispatcher_module,
                        "execute_ready_pending_context",
                    ) as exec:
                        exec.return_value = ProcessedIntent(
                            intent="modificar_producto",
                            source_text="x",
                            status="executed",
                            recognizer="modificar_producto_recognizer",
                            handler="modificar_producto",
                            resolved_data={},
                            requirements=[],
                            candidate_ids=[],
                        )
                        result = dispatch_pending_context(db, session, "x")

        exec.assert_called_once()
        self.assertEqual(result.status, "executed")


class PendingContextExecutionModificarProductoTest(unittest.TestCase):
    def test_dispatches_modificar_producto_to_handler(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        state = MagicMock()
        state.active = _ready_modificar_intent()

        with patch.object(
            pending_execution_module, "load_pending_state", return_value=state
        ):
            with patch.object(
                pending_execution_module, "execute_modificar_producto"
            ) as mod_exec:
                with patch.object(
                    pending_execution_module, "clear_pending_context"
                ):
                    mod_exec.return_value = ProcessedIntent(
                        intent="modificar_producto",
                        source_text="x",
                        status="executed",
                        recognizer="modificar_producto_recognizer",
                        handler="modificar_producto",
                        resolved_data={},
                        requirements=[],
                        candidate_ids=[],
                    )
                    result = execute_ready_pending_context(db, session)

        mod_exec.assert_called_once()
        self.assertEqual(result[0].status, "executed")

    def test_does_not_invoke_other_handlers(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        state = MagicMock()
        state.active = _ready_modificar_intent()

        with patch.object(
            pending_execution_module, "load_pending_state", return_value=state
        ):
            with patch.object(
                pending_execution_module, "execute_agregar_producto"
            ) as agr_exec:
                with patch.object(
                    pending_execution_module, "execute_quitar_producto"
                ) as quit_exec:
                    with patch.object(
                        pending_execution_module, "execute_modificar_producto"
                    ) as mod_exec:
                        with patch.object(
                            pending_execution_module, "clear_pending_context"
                        ):
                            mod_exec.return_value = ProcessedIntent(
                                intent="modificar_producto",
                                source_text="x",
                                status="executed",
                                recognizer="modificar_producto_recognizer",
                                handler="modificar_producto",
                                resolved_data={},
                                requirements=[],
                                candidate_ids=[],
                            )
                            execute_ready_pending_context(db, session)

        mod_exec.assert_called_once()
        agr_exec.assert_not_called()
        quit_exec.assert_not_called()


class ContextTypeResolverModificarProductoTest(unittest.TestCase):
    def test_modificar_producto_returns_product_modification(self):
        intent = _pending_modificar_intent()
        self.assertEqual(
            resolve_context_type(intent), ContextType.PRODUCT_MODIFICATION
        )

    def test_agregar_producto_still_returns_product_selection(self):
        intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id", status="pending", value=None
                )
            ],
            candidate_ids=[1, 2],
        )
        self.assertEqual(
            resolve_context_type(intent), ContextType.PRODUCT_SELECTION
        )

    def test_quitar_producto_still_returns_order_line_selection(self):
        intent = ProcessedIntent(
            intent="quitar_producto",
            source_text="x",
            status="pending_resolution",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[1],
        )
        self.assertEqual(
            resolve_context_type(intent), ContextType.ORDER_LINE_SELECTION
        )


if __name__ == "__main__":
    unittest.main()
