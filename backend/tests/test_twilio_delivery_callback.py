"""Phase-5.6 Twilio delivery callback focused tests.

Coverage:

1. Invalid / missing / tampered signatures return ``403`` with zero
   database calls.
2. Valid signed callbacks advance only the permitted states;
   stale / duplicate / unknown callbacks are idempotent no-ops.
3. Static module / transaction boundaries: the callback route never
   calls transaction-control methods and never logs the raw body or
   the signature.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from backend.dependencies import get_session
from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundProviderMessageState,
)
from backend.services.exceptions import (
    InvalidTwilioDeliveryCallbackForm,
)
from backend.services.twilio_delivery_callback_adapter import (
    TwilioDeliveryCallbackEnvelope,
    extract_envelope,
)
from backend.services.twilio_delivery_callback_service import (
    TwilioDeliveryCallbackService,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


TOKEN = "test-auth-token"
BASE_URL = "https://example.test"
ROUTE = "/webhooks/twilio/whatsapp/status"


def _sign(form: dict[str, str]) -> str:
    validator = RequestValidator(TOKEN)
    return validator.compute_signature(f"{BASE_URL}{ROUTE}", form)


def _build_outbox_row(
    *,
    outbox_id: int = 1,
    estado: str = OutboundProviderMessageState.ACCEPTED.value,
    provider_sid: str = "SM-ABC",
) -> MensajeProveedorSaliente:
    from datetime import datetime, timezone

    row = MensajeProveedorSaliente(
        id=outbox_id,
        proveedor="twilio",
        recepcion_mensaje_proveedor_id=10,
        destinatario_e164="+5491155556666",
        cuerpo="hola",
        sequence=0,
        estado=estado,
        identificador_proveedor=provider_sid,
        intentos=1,
        proximo_intento_en=None,
        token_lease=None,
        lease_expira_en=None,
        categoria_ultimo_fallo=None,
        codigo_ultimo_fallo=None,
        estado_proveedor=None,
        estado_proveedor_en=None,
        fecha_creacion=datetime.now(tz=timezone.utc),
    )
    return row


class CallbackSignatureTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL

    def _client(self) -> TestClient:
        import backend.routers.twilio_delivery_callback as router_module

        app = FastAPI()
        app.include_router(router_module.router)
        db = MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db
        return TestClient(app)

    def test_invalid_signature_returns_403(self) -> None:
        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "delivered"}
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ):
            response = client.post(
                ROUTE, data=form, headers={"X-Twilio-Signature": "bad"}
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")

    def test_missing_signature_returns_403(self) -> None:
        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "delivered"}
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ):
            response = client.post(ROUTE, data=form)
        self.assertEqual(response.status_code, 403)

    def test_missing_configuration_returns_403(self) -> None:
        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "delivered"}
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=None, twilio_webhook_base_url=None
            ),
        ):
            response = client.post(
                ROUTE, data=form, headers={"X-Twilio-Signature": "any"}
            )
        self.assertEqual(response.status_code, 403)


class CallbackServiceMonotonicTest(unittest.TestCase):
    def test_accepted_to_delivered_transition_applies(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.find_by_provider_sid.return_value = _build_outbox_row()
        outbox_repo.record_provider_status.return_value = True

        service = TwilioDeliveryCallbackService(db_session, outbox_repo=outbox_repo)
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor="SM-ABC",
            message_status="delivered",
        )

        self.assertEqual(result.outcome.value, "applied")
        self.assertEqual(
            result.estado_anterior,
            OutboundProviderMessageState.ACCEPTED.value,
        )
        self.assertEqual(
            result.estado_nuevo,
            OutboundProviderMessageState.DELIVERED.value,
        )

    def test_duplicate_delivered_callback_is_noop(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.find_by_provider_sid.return_value = _build_outbox_row(
            estado=OutboundProviderMessageState.DELIVERED.value
        )

        service = TwilioDeliveryCallbackService(db_session, outbox_repo=outbox_repo)
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor="SM-ABC",
            message_status="delivered",
        )

        self.assertEqual(result.outcome.value, "duplicate")
        outbox_repo.record_provider_status.assert_not_called()

    def test_regression_from_delivered_to_failed_is_noop(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.find_by_provider_sid.return_value = _build_outbox_row(
            estado=OutboundProviderMessageState.DELIVERED.value
        )

        service = TwilioDeliveryCallbackService(db_session, outbox_repo=outbox_repo)
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor="SM-ABC",
            message_status="failed",
        )

        self.assertEqual(result.outcome.value, "regression")
        outbox_repo.record_provider_status.assert_not_called()

    def test_unknown_sid_is_noop(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.find_by_provider_sid.return_value = None

        service = TwilioDeliveryCallbackService(db_session, outbox_repo=outbox_repo)
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor="SM-UNKNOWN",
            message_status="delivered",
        )

        self.assertEqual(result.outcome.value, "unknown")
        outbox_repo.record_provider_status.assert_not_called()

    def test_unknown_status_is_noop(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")

        service = TwilioDeliveryCallbackService(db_session, outbox_repo=outbox_repo)
        result = service.apply_callback(
            proveedor="twilio",
            identificador_proveedor="SM-ABC",
            message_status="weird",
        )

        self.assertEqual(result.outcome.value, "unknown")
        outbox_repo.find_by_provider_sid.assert_not_called()


class CallbackAcceptedRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL

    def _client(self, *, session: Any | None = None) -> TestClient:
        import backend.routers.twilio_delivery_callback as router_module

        app = FastAPI()
        app.include_router(router_module.router)
        db = session if session is not None else MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db
        return TestClient(app)

    def test_valid_signed_delivered_callback_returns_204(self) -> None:
        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "delivered"}
        signature = _sign(form)
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ), patch(
            "backend.routers.twilio_delivery_callback.TwilioDeliveryCallbackService"
        ) as service_cls:
            service = MagicMock()
            service.apply_callback.return_value = MagicMock(
                outcome=MagicMock(value="applied"),
                mensaje_id=1,
                estado_anterior="accepted",
                estado_nuevo="delivered",
            )
            service_cls.return_value = service

            response = client.post(
                ROUTE, data=form, headers={"X-Twilio-Signature": signature}
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        service.apply_callback.assert_called_once_with(
            proveedor="twilio",
            identificador_proveedor="SM-ABC",
            message_status="delivered",
        )

    def test_malformed_form_after_valid_signature_returns_204(self) -> None:
        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "  "}
        signature = _sign(form)
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ):
            response = client.post(
                ROUTE, data=form, headers={"X-Twilio-Signature": signature}
            )

        self.assertEqual(response.status_code, 204)


class CallbackDatabaseTechnicalFailureEmissionTest(unittest.TestCase):
    """Blocker 1 regression for the callback path: when the
    callback service raises a real ``SQLAlchemyError``, the route
    MUST emit a valid, queryable ``database_technical_failure``
    event belonging to ``database_technical_boundary``. It MUST
    NOT degrade to ``observability_emit_failed``.
    """

    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL

    def _client(self) -> TestClient:
        import backend.routers.twilio_delivery_callback as router_module

        app = FastAPI()
        app.include_router(router_module.router)
        db = MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db
        return TestClient(app)

    def test_sqlalchemy_error_emits_database_event(self) -> None:
        from sqlalchemy.exc import OperationalError

        client = self._client()
        form = {"MessageSid": "SM-ABC", "MessageStatus": "delivered"}
        signature = _sign(form)
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ), patch(
            "backend.routers.twilio_delivery_callback.TwilioDeliveryCallbackService"
        ) as service_cls, contextlib.redirect_stdout(
            io.StringIO()
        ) as captured:
            from backend.observability import parse_event

            service = MagicMock()
            service.apply_callback.side_effect = OperationalError(
                "stmt", {}, RuntimeError("orig")
            )
            service_cls.return_value = service

            with self.assertRaises(OperationalError):
                client.post(
                    ROUTE,
                    data=form,
                    headers={"X-Twilio-Signature": signature},
                )

        lines = [
            line for line in captured.getvalue().splitlines() if line.strip()
        ]
        assert lines, "no event lines captured on stdout"
        event = parse_event(lines[-1])
        self.assertEqual(event["event"], "database_technical_failure")
        self.assertEqual(
            event["component"], "database_technical_boundary"
        )
        self.assertEqual(event["failure_category"], "connection")
        self.assertEqual(event["exception_type"], "OperationalError")
        self.assertNotEqual(event["event"], "observability_emit_failed")


class CallbackEnvelopeTest(unittest.TestCase):
    def test_canonicalizes_status(self) -> None:
        envelope = extract_envelope(
            {"MessageSid": "SM-1", "MessageStatus": "DELIVERED"}
        )
        self.assertEqual(
            envelope, TwilioDeliveryCallbackEnvelope(
                message_sid="SM-1", message_status="delivered"
            )
        )

    def test_missing_message_sid_rejected(self) -> None:
        with self.assertRaises(InvalidTwilioDeliveryCallbackForm):
            extract_envelope({"MessageStatus": "delivered"})

    def test_unknown_status_rejected(self) -> None:
        with self.assertRaises(InvalidTwilioDeliveryCallbackForm):
            extract_envelope(
                {"MessageSid": "SM-1", "MessageStatus": "weird-status"}
            )


class CallbackRouteModuleBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL

    def test_router_does_not_call_transaction_methods(self) -> None:
        import backend.routers.twilio_delivery_callback as router_module

        source = inspect.getsource(router_module)
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.begin",
            "db.close",
            "db.refresh",
            "db.expire",
            "session.commit",
            "session.rollback",
            "session.flush",
            "session.begin",
            "session.close",
            "session.refresh",
            "session.expire",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_router_logs_no_sensitive_provider_field(self) -> None:
        import backend.routers.twilio_delivery_callback as router_module

        source = inspect.getsource(router_module)
        for forbidden in (
            "extra=auth_token",
            "extra=x_twilio_signature",
            "extra=Body",
            "extra=MessageSid",
            "extra=MessageStatus",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_router_has_single_post_decorator(self) -> None:
        import backend.routers.twilio_delivery_callback as router_module

        source = inspect.getsource(router_module)
        self.assertEqual(source.count("@router.post("), 1)
        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertNotIn(f"@router.{method}", source)

    def test_router_module_all_is_limited(self) -> None:
        import backend.routers.twilio_delivery_callback as router_module

        self.assertEqual(
            set(router_module.__all__),
            {
                "ROUTE_PATH",
                "post_twilio_whatsapp_status",
                "read_full_form",
                "router",
            },
        )


class CallbackAdapterModuleBoundaryTest(unittest.TestCase):
    def test_adapter_does_not_import_sqlalchemy_or_repository(self) -> None:
        path = (
            REPO_ROOT
            / "backend"
            / "services"
            / "twilio_delivery_callback_adapter.py"
        )
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "sqlalchemy",
            "from backend.repositories",
            "MensajeProveedorSalienteRepository",
            "from backend.models",
            "from backend.routers",
            "from backend.intents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)