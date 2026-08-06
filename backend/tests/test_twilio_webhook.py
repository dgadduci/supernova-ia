"""Focused tests for the Phase-5.5 Twilio inbound webhook route.

The route is the only HTTP surface for the new provider ingress.
These tests cover the six documented outcomes using the FastAPI
``TestClient`` with dependency overrides:

1. Valid signed dedicated delivery → ``200`` acknowledgement TwiML
   after the coordinator reports ``processed``.
2. Tampered / missing signature → ``403`` with empty body and zero
   downstream calls.
3. Pre-core business rejections (unknown client, unknown channel,
   shared channel, unavailable commerce) → ``200`` safe control
   TwiML with no coordinator call.
4. Duplicate committed receipt → ``200`` empty ``<Response/>``
   TwiML with no pipeline or session staging.
5. ``invalid_context`` from the coordinator → ``200`` safe control
   TwiML with no fallback to a different commerce.
6. Coordinator technical exception → propagated as ``500``
   (Starlette default), never translated into a business outcome.

The tests inject a real signature computed by the Twilio SDK
``RequestValidator`` for the ``valid`` cases and force the SDK
validation to fail for the tampering cases. The database session
is a ``MagicMock`` so the router cannot perform real SQL
operations; ``ClienteRepository.get_by_whatsapp`` and the channel
resolver are wired to return the appropriate fixtures.
"""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import backend.routers.twilio_webhook as router_module
from backend.dependencies import get_session
from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageOutcome,
    ProviderInboundMessageStatus,
)

ROUTE = router_module.ROUTE_PATH
TOKEN = "test-auth-token"
BASE_URL = "https://example.test"


def _sign(form: dict[str, str]) -> str:
    validator = RequestValidator(TOKEN)
    url = f"{BASE_URL}{ROUTE}"
    return validator.compute_signature(url, form)


class _StubSettings:
    twilio_auth_token: str | None
    twilio_webhook_base_url: str | None

    def __init__(
        self,
        auth_token: str | None = TOKEN,
        base_url: str | None = BASE_URL,
    ) -> None:
        self.twilio_auth_token = auth_token
        self.twilio_webhook_base_url = base_url


def _build_client(*, db_session: Any | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router)

    session = db_session if db_session is not None else MagicMock(name="DatabaseSession")

    def override_get_session() -> Any:
        return session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def _settings(**overrides: Any) -> _StubSettings:
    return _StubSettings(**overrides)


def _build_outcome(
    *,
    status: ProviderInboundMessageStatus,
    canal_id: int = 1,
    cliente_id: int = 2,
    comercio_id: int = 3,
    resolution_source: str = "first_processing",
) -> ProviderInboundMessageOutcome:
    return ProviderInboundMessageOutcome(
        status=status,
        canal_id=canal_id,
        cliente_id=cliente_id,
        comercio_id=comercio_id,
        proveedor="twilio",
        identificador_recepcion="SM-ABC",
        receipt_id=None,
        session_id=None,
        processed_intents=(),
        resolution_source=resolution_source,
    )


class _ResolverChannelMock:
    """Helper that wires the channel-resolver fixture for the route."""

    def __init__(self, resolution_status: str, *, canal_id: int | None = 1, comercio_id: int | None = 3) -> None:
        self._status = resolution_status
        self._canal_id = canal_id
        self._comercio_id = comercio_id

    def __call__(self, _session: Any, _to: str) -> tuple[int | None, int | None]:
        if self._status == "resolved":
            return self._canal_id, self._comercio_id
        return None, None


class WebhookHappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL

        self.db = MagicMock(name="DatabaseSession")

        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.whatsapp = "+5491155556666"
        cliente.activo = True

        canal = MagicMock(name="CanalWhatsapp")
        canal.id = 1
        canal.activo = True
        canal.mode = CanalWhatsappMode.DEDICATED
        canal.id_comercio_exclusivo = 3

        self.cliente = cliente
        self.canal = canal

        self._settings = _settings()
        self.client = _build_client(db_session=self.db)
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)

    def _patch_resolver(self) -> Any:
        from backend.services.commerce_channel_resolver import (
            DedicatedResolution,
            ResolutionStatus,
        )

        canal = self.canal

        def fake_resolve_dedicated(
            self: Any,
            provider: str,
            destination: str,
        ) -> DedicatedResolution:
            return DedicatedResolution(
                status=ResolutionStatus.RESOLVED,
                channel_id=int(canal.id),
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=int(canal.id_comercio_exclusivo),
                resolution_source="destination_number",
            )

        return patch.object(
            router_module.CommerceChannelResolver,
            "resolve_dedicated",
            new=fake_resolve_dedicated,
        )

    def test_first_processing_returns_empty_twiml(self) -> None:
        """Phase 5.6: a first committed receipt returns empty
        TwiML — the durable outbox, not TwiML, is the delivery
        contract. The endpoint MUST NOT embed the business
        response in the TwiML payload."""
        cliente_repo = MagicMock(name="ClienteRepository")
        cliente_repo.get_by_whatsapp.return_value = self.cliente

        outcome = _build_outcome(
            status=ProviderInboundMessageStatus.PROCESSED,
            canal_id=int(self.canal.id),
            cliente_id=int(self.cliente.id),
            comercio_id=int(self.canal.id_comercio_exclusivo),
            resolution_source="first_processing",
        )

        coordinator = MagicMock(name="ProviderInboundMessageCoordinator")
        coordinator.process.return_value = outcome

        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Response />", response.text)
        self.assertNotIn("<Message>", response.text)

        coordinator.process.assert_called_once()
        command = coordinator.process.call_args[0][0]
        self.assertEqual(command.proveedor, "twilio")
        self.assertEqual(command.identificador_recepcion, "SM-ABC")
        self.assertEqual(command.canal_id, int(self.canal.id))
        self.assertEqual(command.cliente_id, int(self.cliente.id))
        self.assertEqual(
            command.comercio_id, int(self.canal.id_comercio_exclusivo)
        )
        self.assertEqual(command.mensaje, "hola")
        self.assertEqual(command.destinatario_e164, "+5491155556666")

        self._assert_no_transaction_calls()

    def _assert_no_transaction_calls(self) -> None:
        for method in ("commit", "rollback", "flush", "begin", "close", "refresh", "expire"):
            with self.subTest(method=method):
                getattr(self.db, method).assert_not_called()


class WebhookSignatureFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.db = MagicMock(name="DatabaseSession")
        self._settings = _settings()
        self.client = _build_client(db_session=self.db)
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)
        self.cliente_repo = MagicMock(name="ClienteRepository")
        self.coordinator = MagicMock(name="ProviderInboundMessageCoordinator")

    def _assert_no_transaction_calls(self) -> None:
        for method in ("commit", "rollback", "flush", "begin", "close", "refresh", "expire"):
            with self.subTest(method=method):
                getattr(self.db, method).assert_not_called()

    def test_missing_signature_returns_403(self) -> None:
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(ROUTE, data=self.form)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")
        self.cliente_repo.get_by_whatsapp.assert_not_called()
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_tampered_body_returns_403(self) -> None:
        tampered = dict(self.form)
        tampered["Body"] = "adulterado"
        real_validator = RequestValidator(TOKEN)
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=real_validator
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=tampered,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")
        self.cliente_repo.get_by_whatsapp.assert_not_called()
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_missing_configuration_returns_403(self) -> None:
        with patch.object(
            router_module,
            "load_settings",
            return_value=_settings(auth_token=None, base_url=None),
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")
        self.cliente_repo.get_by_whatsapp.assert_not_called()
        self.coordinator.process.assert_not_called()


class WebhookBusinessRejectionTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.db = MagicMock(name="DatabaseSession")
        self._settings = _settings()
        self.client = _build_client(db_session=self.db)
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)
        self.cliente_repo = MagicMock(name="ClienteRepository")
        self.coordinator = MagicMock(name="ProviderInboundMessageCoordinator")

    def _patch_resolver(self, *, resolution: str) -> Any:
        from backend.services.commerce_channel_resolver import (
            DedicatedResolution,
            ResolutionStatus,
        )

        if resolution == "resolved":
            target_status = ResolutionStatus.RESOLVED
            channel_id: int | None = 1
            comercio_id: int | None = 3
            source = "destination_number"
        elif resolution == "shared":
            target_status = ResolutionStatus.REQUIRES_SHARED_ROUTING
            channel_id = 1
            comercio_id = None
            source = "shared_channel"
        elif resolution == "unknown":
            target_status = ResolutionStatus.UNKNOWN_CHANNEL
            channel_id = None
            comercio_id = None
            source = "no_active_channel"
        elif resolution == "invalid":
            target_status = ResolutionStatus.INVALID_DESTINATION
            channel_id = None
            comercio_id = None
            source = "destination_normalization"
        elif resolution == "inactive":
            target_status = ResolutionStatus.INACTIVE_CHANNEL
            channel_id = 1
            comercio_id = None
            source = "inactive_channel"
        else:
            target_status = ResolutionStatus.UNAVAILABLE_COMMERCE
            channel_id = 1
            comercio_id = None
            source = "no_exclusive_commerce"

        def fake_resolve_dedicated(
            self: Any,
            provider: str,
            destination: str,
        ) -> DedicatedResolution:
            return DedicatedResolution(
                status=target_status,
                channel_id=channel_id,
                routing_mode=CanalWhatsappMode.DEDICATED
                if target_status is ResolutionStatus.RESOLVED
                else CanalWhatsappMode.SHARED
                if target_status is ResolutionStatus.REQUIRES_SHARED_ROUTING
                else None,
                comercio_id=comercio_id,
                resolution_source=source,
            )

        return patch.object(
            router_module.CommerceChannelResolver,
            "resolve_dedicated",
            new=fake_resolve_dedicated,
        )

    def _assert_no_transaction_calls(self) -> None:
        for method in ("commit", "rollback", "flush", "begin", "close", "refresh", "expire"):
            with self.subTest(method=method):
                getattr(self.db, method).assert_not_called()

    def test_unknown_client_returns_safe_control_twiml(self) -> None:
        self.cliente_repo.get_by_whatsapp.return_value = None
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Message>", response.text)
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_inactive_client_returns_safe_control_twiml(self) -> None:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = False
        self.cliente_repo.get_by_whatsapp.return_value = cliente
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Message>", response.text)
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_shared_channel_returns_safe_control_twiml(self) -> None:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = True
        self.cliente_repo.get_by_whatsapp.return_value = cliente
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(
            resolution="shared"
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Message>", response.text)
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_unknown_destination_returns_safe_control_twiml(self) -> None:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = True
        self.cliente_repo.get_by_whatsapp.return_value = cliente
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(
            resolution="unknown"
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Message>", response.text)
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_invalid_destination_returns_safe_control_twiml(self) -> None:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = True
        self.cliente_repo.get_by_whatsapp.return_value = cliente
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(
            resolution="invalid"
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Message>", response.text)
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()


class WebhookDuplicateAndInvalidContextTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.db = MagicMock(name="DatabaseSession")
        self._settings = _settings()
        self.client = _build_client(db_session=self.db)
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)

    def _wire(self, *, status: ProviderInboundMessageStatus, source: str) -> tuple[MagicMock, MagicMock]:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = True
        cliente_repo = MagicMock(name="ClienteRepository")
        cliente_repo.get_by_whatsapp.return_value = cliente

        coordinator = MagicMock(name="ProviderInboundMessageCoordinator")
        coordinator.process.return_value = _build_outcome(
            status=status,
            resolution_source=source,
        )
        return cliente_repo, coordinator

    def _patch_resolver(self) -> Any:
        from backend.services.commerce_channel_resolver import (
            DedicatedResolution,
            ResolutionStatus,
        )

        def fake_resolve_dedicated(
            self: Any,
            provider: str,
            destination: str,
        ) -> DedicatedResolution:
            return DedicatedResolution(
                status=ResolutionStatus.RESOLVED,
                channel_id=1,
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=3,
                resolution_source="destination_number",
            )

        return patch.object(
            router_module.CommerceChannelResolver,
            "resolve_dedicated",
            new=fake_resolve_dedicated,
        )

    def _assert_no_transaction_calls(self) -> None:
        for method in ("commit", "rollback", "flush", "begin", "close", "refresh", "expire"):
            with self.subTest(method=method):
                getattr(self.db, method).assert_not_called()

    def test_duplicate_receipt_returns_empty_twiml(self) -> None:
        cliente_repo, coordinator = self._wire(
            status=ProviderInboundMessageStatus.ALREADY_PROCESSED,
            source="duplicate_receipt",
        )
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Response />", response.text)
        self.assertNotIn("<Message>", response.text)
        coordinator.process.assert_called_once()
        self._assert_no_transaction_calls()

    def test_invalid_context_returns_safe_control_twiml(self) -> None:
        cliente_repo, coordinator = self._wire(
            status=ProviderInboundMessageStatus.INVALID_CONTEXT,
            source="dedicated_authority",
        )
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Message>", response.text)
        coordinator.process.assert_called_once()
        self._assert_no_transaction_calls()


class WebhookTechnicalFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.db = MagicMock(name="DatabaseSession")
        self._settings = _settings()
        self.error_client = TestClient(
            self._build_app(),
            raise_server_exceptions=False,
        )
        self.client = _build_client(db_session=self.db)
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(router_module.router)
        app.dependency_overrides[get_session] = lambda: self.db
        return app

    def test_coordinator_runtime_error_propagates_as_500(self) -> None:
        cliente = MagicMock(name="Cliente")
        cliente.id = 2
        cliente.activo = True
        cliente_repo = MagicMock(name="ClienteRepository")
        cliente_repo.get_by_whatsapp.return_value = cliente
        coordinator = MagicMock(name="ProviderInboundMessageCoordinator")
        coordinator.process.side_effect = RuntimeError("coordinator boom")
        from backend.services.commerce_channel_resolver import (
            DedicatedResolution,
            ResolutionStatus,
        )

        def fake_resolve_dedicated(
            self: Any,
            provider: str,
            destination: str,
        ) -> DedicatedResolution:
            return DedicatedResolution(
                status=ResolutionStatus.RESOLVED,
                channel_id=1,
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=3,
                resolution_source="destination_number",
            )

        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=MagicMock(name="Validator")
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=cliente_repo,
        ), patch.object(
            router_module.CommerceChannelResolver,
            "resolve_dedicated",
            new=fake_resolve_dedicated,
        ), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=coordinator,
        ):
            response = self.error_client.post(
                ROUTE,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("coordinator boom", response.text)


class WebhookModuleBoundaryTest(unittest.TestCase):
    def test_router_does_not_call_transaction_methods(self) -> None:
        import inspect

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

    def test_router_does_not_log_sensitive_provider_payload(self) -> None:
        import inspect

        source = inspect.getsource(router_module)
        forbidden_log_fields = {
            "auth_token",
            "x_twilio_signature",
            "sender",
            "destination",
            "Body",
        }
        for forbidden in forbidden_log_fields:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    f"extra={forbidden}",
                    source,
                    f"router must not log the sensitive provider field: {forbidden}",
                )

    def test_router_passes_signature_to_validator_only(self) -> None:
        import inspect

        source = inspect.getsource(router_module)
        # The signature is consumed by the SDK validator only. Logging
        # discipline is enforced by
        # ``test_router_does_not_log_sensitive_provider_payload``.
        self.assertIn(
            "signature=x_twilio_signature",
            source,
            "signature must reach the validator",
        )

    def test_router_exposes_only_safe_endpoint(self) -> None:
        import inspect

        source = inspect.getsource(router_module)
        self.assertEqual(source.count("@router.post("), 1)
        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertNotIn(f"@router.{method}", source)

    def test_router_module_all_is_limited(self) -> None:
        self.assertEqual(
            set(router_module.__all__),
            {
                "ROUTE_PATH",
                "post_twilio_whatsapp_inbound",
                "read_full_form",
                "router",
            },
        )

    def test_public_endpoint_is_synchronous(self) -> None:
        """The Twilio inbound handler must remain a synchronous
        ``def`` so it conforms to the project's FastAPI surface and
        avoids mixing the async form read with the rest of the
        validation pipeline. The async form read is isolated in the
        :func:`read_full_form` dependency, the only async seam in
        the module."""
        import inspect

        self.assertFalse(
            inspect.iscoroutinefunction(router_module.post_twilio_whatsapp_inbound),
            "post_twilio_whatsapp_inbound must remain a synchronous handler",
        )
        self.assertTrue(
            inspect.iscoroutinefunction(router_module.read_full_form),
            "read_full_form must remain the only async seam in the module",
        )
        source = inspect.getsource(router_module)
        # No ``await`` may appear inside the handler body. The
        # dependency is the single place that ``await``s the form.
        handler_block = source[
            source.index("def post_twilio_whatsapp_inbound(") : source.index(
                "\n\n\ndef _xml_response"
            )
        ]
        self.assertNotIn(
            "await ",
            handler_block,
            "the synchronous handler must not use ``await``; "
            "the async form read belongs to the read_full_form dependency",
        )
        self.assertNotIn(
            "request.form()",
            handler_block,
            "the handler must read the form via the dependency, not directly",
        )

    def test_full_form_dependency_preserves_signed_query_branch(self) -> None:
        """The async dependency must be the single source of the
        ``Mapping[str, str]`` delivered to the synchronous handler,
        and the handler must keep reading the actual query string
        from the ``Request`` so the canonical signature URL still
        includes the signed query branch."""
        import inspect

        source = inspect.getsource(router_module)
        # The dependency exists and reads the complete form.
        self.assertIn(
            "async def read_full_form(request: Request)",
            source,
            "read_full_form must be the async dependency that reads the full form",
        )
        self.assertIn(
            "await request.form()",
            source,
            "read_full_form must await the complete submitted form",
        )
        # The handler is wired to the dependency, not to ``request.form()``.
        self.assertIn(
            "form: Mapping[str, str] = Depends(read_full_form)",
            source,
            "the handler must consume the form through the read_full_form dependency",
        )
        # The query string is still taken from the actual ``Request`` so
        # the signed query branch is preserved end-to-end.
        self.assertIn(
            "query_string = request.url.query",
            source,
            "the handler must read the actual query string from the Request",
        )
        # The validator still receives the full form and the query string.
        self.assertIn(
            "form=form,",
            source,
            "the handler must forward the complete form to validate_request",
        )
        self.assertIn(
            "query_string=query_string,",
            source,
            "the handler must forward the actual query string to validate_request",
        )

    def test_full_form_dependency_does_no_downstream_work(self) -> None:
        """The async dependency only reads the form. It must not
        touch the database, the resolver, the coordinator, the
        adapter or any logging facility, so signature validation
        remains the first downstream side-effect."""
        import inspect

        source = inspect.getsource(router_module)
        dep_start = source.index("async def read_full_form(")
        dep_end = source.index("\n\n\n", dep_start)
        dep_block = source[dep_start:dep_end]
        for forbidden in (
            "load_settings",
            "ClienteRepository",
            "CommerceChannelResolver",
            "ProviderInboundMessageCoordinator",
            "validate_request",
            "extract_envelope",
            "_resolve_cliente",
            "_resolve_destination",
            "logger.",
            "_validator_factory",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    dep_block,
                    "read_full_form must not perform any downstream work: "
                    f"{forbidden}",
                )


class WebhookFullFormSignatureTest(unittest.TestCase):
    """Twilio signs every POST parameter; the router must validate the
    signature against the complete submitted form and the actual
    query string instead of truncating to the four documented
    fields. The tests in this class use the real Twilio SDK
    ``RequestValidator`` so the actual HMAC verification exercises
    the full-form and query-string branches."""

    def setUp(self) -> None:
        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.db = MagicMock(name="DatabaseSession")
        self._settings = _settings()
        self.client = _build_client(db_session=self.db)

        self.cliente = MagicMock(name="Cliente")
        self.cliente.id = 2
        self.cliente.whatsapp = "+5491155556666"
        self.cliente.activo = True

        self.canal = MagicMock(name="CanalWhatsapp")
        self.canal.id = 1
        self.canal.activo = True
        self.canal.mode = CanalWhatsappMode.DEDICATED
        self.canal.id_comercio_exclusivo = 3

        self.cliente_repo = MagicMock(name="ClienteRepository")
        self.cliente_repo.get_by_whatsapp.return_value = self.cliente

        self.coordinator = MagicMock(name="ProviderInboundMessageCoordinator")
        self.coordinator.process.return_value = _build_outcome(
            status=ProviderInboundMessageStatus.PROCESSED,
            canal_id=int(self.canal.id),
            cliente_id=int(self.cliente.id),
            comercio_id=int(self.canal.id_comercio_exclusivo),
            resolution_source="first_processing",
        )

    def _patch_resolver(self) -> Any:
        from backend.services.commerce_channel_resolver import (
            DedicatedResolution,
            ResolutionStatus,
        )

        canal = self.canal

        def fake_resolve_dedicated(
            self: Any,
            provider: str,
            destination: str,
        ) -> DedicatedResolution:
            return DedicatedResolution(
                status=ResolutionStatus.RESOLVED,
                channel_id=int(canal.id),
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=int(canal.id_comercio_exclusivo),
                resolution_source="destination_number",
            )

        return patch.object(
            router_module.CommerceChannelResolver,
            "resolve_dedicated",
            new=fake_resolve_dedicated,
        )

    def _assert_no_transaction_calls(self) -> None:
        for method in (
            "commit",
            "rollback",
            "flush",
            "begin",
            "close",
            "refresh",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.db, method).assert_not_called()

    def test_valid_signature_with_extra_twilio_parameters(self) -> None:
        """Twilio always submits ``AccountSid``, ``ApiVersion``,
        ``NumMedia``, ``SmsMessageSid``, ``SmsStatus`` and
        ``MessagingServiceSid`` alongside the four documented
        fields. The router must validate the signature over the
        complete form so legitimate requests with extras do not
        return 403."""
        form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "AccountSid": "AC-EXTRA",
            "ApiVersion": "2010-04-01",
            "NumMedia": "0",
            "SmsMessageSid": "SM-EXTRA",
            "SmsStatus": "received",
            "MessagingServiceSid": "MG-EXTRA",
        }
        signature = _sign(form)
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=RequestValidator(TOKEN)
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=form,
                headers={"X-Twilio-Signature": signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Response />", response.text)
        self.assertNotIn("<Message>", response.text)
        self.coordinator.process.assert_called_once()
        command = self.coordinator.process.call_args[0][0]
        self.assertEqual(command.proveedor, "twilio")
        self.assertEqual(command.identificador_recepcion, "SM-ABC")
        self.assertEqual(command.mensaje, "hola")
        self._assert_no_transaction_calls()

    def test_tampered_extra_parameter_returns_403(self) -> None:
        """Mutating any signed parameter (including an extra one
        Twilio added) must fail signature validation with no
        downstream calls."""
        form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "AccountSid": "AC-EXTRA",
            "ApiVersion": "2010-04-01",
            "NumMedia": "0",
        }
        tampered = dict(form)
        tampered["ApiVersion"] = "2099-12-31"
        signature = _sign(form)
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=RequestValidator(TOKEN)
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                ROUTE,
                data=tampered,
                headers={"X-Twilio-Signature": signature},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")
        self.cliente_repo.get_by_whatsapp.assert_not_called()
        self.coordinator.process.assert_not_called()
        self._assert_no_transaction_calls()

    def test_query_string_is_included_in_validation_url(self) -> None:
        """The router must pass the actual query string of the
        request to the SDK validator so the canonical signature URL
        matches what Twilio signed."""
        form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        query_string = "hub=1&foo=bar"
        signed_url = f"{BASE_URL}{ROUTE}?{query_string}"
        signature = RequestValidator(TOKEN).compute_signature(signed_url, form)
        with patch.object(
            router_module, "load_settings", return_value=self._settings
        ), patch.object(
            router_module, "_validator_factory", return_value=RequestValidator(TOKEN)
        ), patch(
            "backend.routers.twilio_webhook.ClienteRepository",
            return_value=self.cliente_repo,
        ), self._patch_resolver(), patch(
            "backend.routers.twilio_webhook.ProviderInboundMessageCoordinator",
            return_value=self.coordinator,
        ):
            response = self.client.post(
                f"{ROUTE}?{query_string}",
                data=form,
                headers={"X-Twilio-Signature": signature},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response />", response.text)
        self.assertNotIn("<Message>", response.text)
        self.coordinator.process.assert_called_once()
        self._assert_no_transaction_calls()


if __name__ == "__main__":
    unittest.main(verbosity=2)
