import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration import (
    incoming_message_response_orchestrator as response_orchestrator_module,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.intents.responses import (
    agregar_producto_response as agregar_response_module,
)
from backend.intents.responses import (
    modificar_producto_response as modificar_response_module,
)
from backend.intents.responses import (
    quitar_producto_response as quitar_response_module,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _intent(intent_name: str, status: str = "rejected") -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent_name,
        source_text="x",
        status=status,  # type: ignore[arg-type]
        recognizer="r",
        handler=intent_name,
        resolved_data={},
        requirements=[],
        candidate_ids=[],
    )


class IncomingMessageResponseOrchestratorModificarProductoTest(unittest.TestCase):
    def test_modificar_producto_routes_to_modificar_builder(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
        ) as proc:
            proc.return_value = [_intent("modificar_producto", "executed")]
            with patch.object(
                response_orchestrator_module,
                "build_modificar_producto_response",
            ) as mod_build:
                with patch.object(
                    response_orchestrator_module,
                    "build_agregar_producto_response",
                ) as agr_build:
                    with patch.object(
                        response_orchestrator_module,
                        "build_quitar_producto_response",
                    ) as quit_build:
                        mod_build.return_value = CustomerResponse(
                            message="OK",
                            intent="modificar_producto",
                            status="executed",
                        )
                        result = process_incoming_message_with_responses(
                            db, session, "x"
                        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "modificar_producto")
        mod_build.assert_called_once()
        agr_build.assert_not_called()
        quit_build.assert_not_called()

    def test_modificar_producto_pending_routes_to_modificar_builder(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
        ) as proc:
            proc.return_value = [
                _intent("modificar_producto", "pending_resolution")
            ]
            with patch.object(
                response_orchestrator_module,
                "build_modificar_producto_response",
            ) as mod_build:
                mod_build.return_value = CustomerResponse(
                    message="¿Cuál?",
                    intent="modificar_producto",
                    status="pending_resolution",
                )
                result = process_incoming_message_with_responses(
                    db, session, "x"
                )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "pending_resolution")
        mod_build.assert_called_once()

    def test_unknown_intent_returns_generic(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
        ) as proc:
            proc.return_value = [_intent("desconocida", "rejected")]
            with patch.object(
                response_orchestrator_module,
                "build_modificar_producto_response",
            ) as mod_build:
                with patch.object(
                    response_orchestrator_module,
                    "build_agregar_producto_response",
                ) as agr_build:
                    with patch.object(
                        response_orchestrator_module,
                        "build_quitar_producto_response",
                    ) as quit_build:
                        result = process_incoming_message_with_responses(
                            db, session, "x"
                        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "desconocida")
        self.assertEqual(result[0].status, "rejected")
        mod_build.assert_not_called()
        agr_build.assert_not_called()
        quit_build.assert_not_called()

    def test_agregar_producto_does_not_invoke_modificar_builder(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
        ) as proc:
            proc.return_value = [_intent("agregar_producto", "executed")]
            with patch.object(
                response_orchestrator_module,
                "build_agregar_producto_response",
            ) as agr_build:
                with patch.object(
                    response_orchestrator_module,
                    "build_modificar_producto_response",
                ) as mod_build:
                    agr_build.return_value = CustomerResponse(
                        message="OK",
                        intent="agregar_producto",
                        status="executed",
                    )
                    result = process_incoming_message_with_responses(
                        db, session, "x"
                    )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "agregar_producto")
        agr_build.assert_called_once()
        mod_build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
