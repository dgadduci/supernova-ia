import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pydantic
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routers.incoming_messages as router_module
from backend.dependencies import get_session
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    GENERIC_MESSAGE,
    process_incoming_message_with_responses,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.schemas.incoming_message import IncomingMessageRequest
from backend.services.exceptions import SessionNotFound

app = FastAPI()
app.include_router(router_module.router)
db = MagicMock(name="DatabaseSession")


def override_get_session():
    return db


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)
error_client = TestClient(app, raise_server_exceptions=False)


class IncomingMessageSchemaTest(unittest.TestCase):
    def test_request_schema_validation(self):
        self.assertEqual(IncomingMessageRequest(message="hola").message, "hola")
        invalid_payloads = (
            {"message": None},
            {"message": 123},
            {"message": "hola", "extra_field": "x"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(pydantic.ValidationError):
                    IncomingMessageRequest.model_validate(payload)


class IncomingMessagesEndpointTest(unittest.TestCase):
    def setUp(self):
        db.reset_mock()

    def assert_no_transaction_calls(self):
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_agregar_producto_happy_path(self, get_active, process):
        session = MagicMock(name="ConversationSession")
        get_active.return_value = session
        process.return_value = [
            CustomerResponse(
                message="Listo, agregué 2 Pizza Mozzarella grande.",
                intent="agregar_producto",
                status="executed",
            )
        ]

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "quiero una pizza"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "responses": [
                    {
                        "message": "Listo, agregué 2 Pizza Mozzarella grande.",
                        "intent": "agregar_producto",
                        "status": "executed",
                    }
                ]
            },
        )
        get_active.assert_called_once_with(1, 2)
        process.assert_called_once_with(db, session, "quiero una pizza")
        self.assert_no_transaction_calls()

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_unsupported_intent_happy_path(self, get_active, process):
        session = MagicMock(name="ConversationSession")
        get_active.return_value = session
        process.return_value = [
            CustomerResponse(
                message=GENERIC_MESSAGE,
                intent="desconocida",
                status="rejected",
            )
        ]

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "asdfgh"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "responses": [
                    {
                        "message": GENERIC_MESSAGE,
                        "intent": "desconocida",
                        "status": "rejected",
                    }
                ]
            },
        )
        self.assertIs(
            router_module.process_incoming_message_with_responses,
            process,
        )
        get_active.assert_called_once_with(1, 2)
        process.assert_called_once_with(db, session, "asdfgh")

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_multi_intent_order_is_preserved(self, get_active, process):
        get_active.return_value = MagicMock(name="ConversationSession")
        responses = [
            CustomerResponse(
                message="Agregado",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="Elegí una opción",
                intent="agregar_producto",
                status="pending_resolution",
            ),
            CustomerResponse(
                message=GENERIC_MESSAGE,
                intent="desconocida",
                status="rejected",
            ),
        ]
        process.return_value = responses

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "mix"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["status"] for item in response.json()["responses"]],
            ["executed", "pending_resolution", "rejected"],
        )
        self.assertEqual(
            [item["message"] for item in response.json()["responses"]],
            [item.message for item in responses],
        )

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_empty_response_list(self, get_active, process):
        get_active.return_value = MagicMock(name="ConversationSession")
        process.return_value = []

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "hola"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"responses": []})

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_session_not_found_returns_404(self, get_active, process):
        exc = SessionNotFound((1, 2))
        get_active.side_effect = exc

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "hola"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": str(exc)})
        process.assert_not_called()
        self.assert_no_transaction_calls()

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_type_error_returns_400(self, get_active, process):
        get_active.return_value = MagicMock(name="ConversationSession")
        process.side_effect = TypeError("message must be a str")

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "message must be a str"})
        self.assert_no_transaction_calls()

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_empty_message_value_error_returns_400(self, get_active, process):
        get_active.return_value = MagicMock(name="ConversationSession")
        process.side_effect = ValueError(
            "message must be a non-empty, non-whitespace string"
        )

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "message must be a non-empty, non-whitespace string"},
        )

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_whitespace_message_value_error_returns_400(
        self, get_active, process
    ):
        get_active.return_value = MagicMock(name="ConversationSession")
        process.side_effect = ValueError(
            "message must be a non-empty, non-whitespace string"
        )

        response = client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "   \n\t  "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "message must be a non-empty, non-whitespace string",
        )

    def test_invalid_payloads_return_422_before_handler(self):
        invalid_payloads = (
            {"message": 123},
            {},
            {"message": "hola", "extra_field": "x"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with patch.object(
                    router_module.SessionService, "get_active"
                ) as get_active, patch.object(
                    router_module,
                    "process_incoming_message_with_responses",
                ) as process:
                    response = client.post(
                        "/comercios/1/clientes/2/incoming-messages",
                        json=payload,
                    )
                    self.assertEqual(response.status_code, 422)
                    get_active.assert_not_called()
                    process.assert_not_called()

    @patch.object(router_module, "process_incoming_message_with_responses")
    @patch.object(router_module.SessionService, "get_active")
    def test_unhandled_exception_propagates_to_default_500(
        self, get_active, process
    ):
        get_active.return_value = MagicMock(name="ConversationSession")
        process.side_effect = RuntimeError("boom")

        response = error_client.post(
            "/comercios/1/clientes/2/incoming-messages",
            json={"message": "hola"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.text, "Internal Server Error")
        self.assertNotIn("boom", response.text)


class IncomingMessagesModuleBoundaryTest(unittest.TestCase):
    def test_router_all_is_limited(self):
        self.assertEqual(router_module.__all__, ["router"])

    def test_schema_all_is_limited(self):
        import backend.schemas.incoming_message as schema_module

        self.assertEqual(
            schema_module.__all__,
            ["IncomingMessageRequest", "IncomingMessageResponse"],
        )

    def test_router_uses_stable_orchestrator_handle(self):
        self.assertIs(
            router_module.process_incoming_message_with_responses,
            process_incoming_message_with_responses,
        )

    def test_router_source_boundaries(self):
        source = Path(router_module.__file__).read_text(encoding="utf-8")
        forbidden = (
            "from backend.old_project",
            "from backend.llm",
            "from backend.repositories",
            "from backend.intents.handlers",
            "from backend.intents.context",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "import requests",
            "import twilio",
            "MessagingResponse",
            "asyncio",
            "async def",
            "await ",
            "logger.",
            "logging.",
            "print(",
            "time.sleep",
            "retry",
            "backoff",
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, source)

        imports = [
            node.module
            for node in ast.parse(source).body
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("backend.intents.orchestration")
        ]
        self.assertEqual(
            imports,
            [
                "backend.intents.orchestration."
                "incoming_message_response_orchestrator"
            ],
        )

    def test_router_has_single_post_decorator(self):
        source = Path(router_module.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("@router.post("), 1)
        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertNotIn(f"@router.{method}", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
