"""Focused tests for the Admin/Pilot emulator inbound bootstrap.

These tests cover the bounded bootstrap action that the panel
exposes to operators who want to start a clean provider-shaped
inbound test from an existing active client and commerce. The
tests exercise the route, the bounded request/response schema and
the server-side resolution carried out by the bootstrap service
helpers — without ever touching a real database, T-C, Twilio or
the worker.

The bootstrap route is intentionally narrow: it must never create
a Session, Pedido, receipt, processing row or outbox row, and it
must never call the coordinator, worker, dispatcher, T-C or Twilio
directly. The dedicated emulator inbound control surface is the
only downstream entry point.
"""
from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routers.admin_pilot_orders as router_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.services.commerce_availability_service import (
    CommerceAvailabilityStatus,
)

CONFIGURED_TOKEN = "pilot-panel-token-for-tests"


def _settings(token: str | None = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(
        **{**base.__dict__, "order_management_admin_token": token}
    )


def _settings_with_emulator_enabled(
    token: str | None = CONFIGURED_TOKEN,
) -> Settings:
    """Build a Settings instance that enables the admin emulator
    action: explicit ``TWILIO_PROVIDER_MODE=emulator``, isolated
    outbound on, and the bounded emulator configuration."""
    base = _settings(token=token)
    return Settings(
        **{**base.__dict__, "twilio_provider_mode": "emulator",
            "commerce_isolated_outbound_enabled": True,
            "twilio_emulator_base_url": "https://emulator.example.test",
            "twilio_emulator_account_sid": "AC" + "1" * 32,
            "twilio_emulator_auth_token": "emulator-auth-token-abc",
            "twilio_emulator_control_token": "control-token-xyz",
            "twilio_emulator_http_timeout_seconds": 5,
        }
    )


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router)
    return app


class _SessionOverride:
    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
        return self._return_value

    def assert_not_called(self) -> None:
        if self.call_count != 0:
            raise AssertionError(
                f"session override was called {self.call_count} time(s)"
            )


def _stub_cliente(*, activo: bool = True, whatsapp: str = "+5491100000001"):
    cliente = SimpleNamespace(
        id=31,
        activo=activo,
        whatsapp=whatsapp,
    )
    return cliente


def _stub_canal(
    *,
    canal_id: int = 5,
    destination: str = "+5491100000099",
    activo: bool = True,
    mode: Any = "dedicated",
    provider: str = "twilio",
):
    canal = SimpleNamespace(
        id=canal_id,
        destination_e164=destination,
        activo=activo,
        mode=mode,
        provider=provider,
    )
    return canal


def _stub_installation():
    return SimpleNamespace(id=1, id_comercio=1, activo=True)


def _stub_active_session():
    return SimpleNamespace(
        id=99,
        id_comercio=1,
        id_cliente=31,
        estado_session="activa",
    )


class BootstrapRouteAuthTest(unittest.TestCase):
    """The bootstrap POST route mounts behind the same panel Basic
    authentication as the rest of the route family. Missing or
    wrong credentials return 401 with no business work."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_missing_credential_returns_401(self) -> None:
        response = self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json={"cliente_id": 31, "comercio_id": 1, "message": "hola"},
            headers={"X-Emulator-Test-Origin": "same-origin"},
        )
        self.assertEqual(response.status_code, 401)
        self.session_override.assert_not_called()


class BootstrapRouteHeaderTest(unittest.TestCase):
    """The bootstrap POST route requires the same-origin custom
    header before any database work runs."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, origin_value):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        if origin_value is not None:
            headers["X-Emulator-Test-Origin"] = origin_value
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json={"cliente_id": 31, "comercio_id": 1, "message": "hola"},
            headers=headers,
        )

    def test_missing_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
        ) as target_mock:
            response = self._post(origin_value=None)
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()

    def test_wrong_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
        ) as target_mock:
            response = self._post(origin_value="attacker.example")
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()


class BootstrapRouteBodyValidationTest(unittest.TestCase):
    """Body validation rejects empty, malformed and oversized
    payloads before any business work runs."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, body, **kwargs):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            headers=headers,
            **kwargs,
        )

    def test_empty_body_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(body=None, json={})
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_non_positive_cliente_id_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={"cliente_id": 0, "comercio_id": 1, "message": "hola"},
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_non_positive_comercio_id_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={"cliente_id": 31, "comercio_id": -1, "message": "hola"},
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_oversized_message_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={
                    "cliente_id": 31,
                    "comercio_id": 1,
                    "message": "x" * 501,
                },
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_empty_message_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={"cliente_id": 31, "comercio_id": 1, "message": ""},
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_extra_field_returns_422(self) -> None:
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={
                    "cliente_id": 31,
                    "comercio_id": 1,
                    "message": "hola",
                    "extra": "x",
                },
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_address_field_is_ignored_returns_422(self) -> None:
        """The browser must not be able to inject phone numbers,
        URLs, credentials or provider-SID-shaped fields; the
        ``extra='forbid'`` schema rejects them."""
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(
                body=None,
                json={
                    "cliente_id": 31,
                    "comercio_id": 1,
                    "message": "hola",
                    "source_e164": "+5491100000001",
                    "destination_e164": "+5491100000099",
                    "control_token": "ctrl",
                    "webhook_url": "https://attacker.example",
                },
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()


class BootstrapRouteBlankMessageTest(unittest.TestCase):
    """``EmulatorBootstrapRequest.min_length=1`` accepts messages
    composed only of ASCII spaces, tabs or newlines; the server-side
    non-blank validator must reject those payloads BEFORE the
    Twilio Emulator is contacted. ``resolve_bootstrap_target``,
    ``build_emulator_control_client`` and the eventual
    ``submit_inbound`` MUST NOT be invoked for any of them."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._router_settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, message: str) -> Any:
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json={"cliente_id": 31, "comercio_id": 1, "message": message},
            headers=headers,
        )

    def _assert_no_downstream_calls(self, message: str) -> None:
        emulator_client = MagicMock(name="EmulatorClient")
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
        ) as target_mock, patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
        ) as session_mock, patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=emulator_client,
        ) as client_mock:
            response = self._post(message=message)
        self.assertEqual(
            response.status_code,
            422,
            msg=f"expected 422 for blank message {message!r}",
        )
        target_mock.assert_not_called()
        session_mock.assert_not_called()
        client_mock.assert_not_called()
        emulator_client.submit_inbound.assert_not_called()

    def test_spaces_only_message_returns_422(self) -> None:
        self._assert_no_downstream_calls("   ")

    def test_tabs_only_message_returns_422(self) -> None:
        self._assert_no_downstream_calls("\t\t\t")

    def test_newline_only_message_returns_422(self) -> None:
        self._assert_no_downstream_calls("\n")

    def test_mixed_whitespace_message_returns_422(self) -> None:
        self._assert_no_downstream_calls(" \t\n\r \t")

    def test_empty_message_returns_422(self) -> None:
        self._assert_no_downstream_calls("")

    def test_validator_preserves_original_message_for_valid_submission(
        self,
    ) -> None:
        """A valid message that contains leading/trailing whitespace
        plus content is forwarded untouched to the emulator. The
        validator only rejects the blank payload; it does not
        normalise a valid submission."""

        class _RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            def submit_inbound(
                self,
                *,
                source_e164: str,
                destination_e164: str,
                body: str,
            ) -> Any:
                self.calls.append(
                    {
                        "source_e164": source_e164,
                        "destination_e164": destination_e164,
                        "body": body,
                    }
                )
                return SimpleNamespace(
                    status="accepted",
                    message_sid="SM-FAKE",
                    synthetic_inbound_id="SYN-INBOUND-FAKE",
                )

        target = SimpleNamespace(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        from backend.services.admin_pilot_emulator_service import (
            EmulatorBootstrapTarget,
        )

        target = EmulatorBootstrapTarget(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        client = _RecordingClient()
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post(message="  hola mundo  ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["body"], "  hola mundo  ")


class BootstrapRouteRevalidationTest(unittest.TestCase):
    """The bootstrap route verifies the exact server-side
    resolution BEFORE invoking the emulator. Any mismatch returns
    the generic rejection without invoking the emulator or any
    business pipeline."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._router_settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, body=None):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json=body
            if body is not None
            else {"cliente_id": 31, "comercio_id": 1, "message": "hola"},
            headers=headers,
        )

    def test_invalid_target_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=None,
        ) as target_mock, patch.object(
            router_module,
            "build_emulator_control_client",
        ) as client_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        target_mock.assert_called_once()
        client_mock.assert_not_called()

    def test_active_session_returns_generic_rejection(self) -> None:
        from backend.services.admin_pilot_emulator_service import (
            EmulatorBootstrapTarget,
        )

        target = EmulatorBootstrapTarget(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=_stub_active_session(),
        ) as session_mock, patch.object(
            router_module,
            "build_emulator_control_client",
        ) as client_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        session_mock.assert_called_once()
        client_mock.assert_not_called()

    def test_emulator_client_disabled_returns_generic_rejection(self) -> None:
        from backend.services.admin_pilot_emulator_service import (
            EmulatorBootstrapTarget,
        )

        target = EmulatorBootstrapTarget(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=None,
        ) as client_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        client_mock.assert_called_once()


class BootstrapRouteHappyPathTest(unittest.TestCase):
    """A valid bootstrap turn invokes the emulator inbound control
    surface exactly once with the server-resolved E.164 addresses,
    the operator message body and a synthetic inbound identifier.
    No coordinator, no worker, no dispatcher, no T-C, no real
    Twilio SDK."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._router_settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, body=None):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json=body
            if body is not None
            else {"cliente_id": 31, "comercio_id": 1, "message": "hola"},
            headers=headers,
        )

    def _build_target(self):
        from backend.services.admin_pilot_emulator_service import (
            EmulatorBootstrapTarget,
        )

        return EmulatorBootstrapTarget(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )

    def test_happy_path_returns_synthetic_inbound_id(self) -> None:
        target = self._build_target()
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SYN-INBOUND-FAKE",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["synthetic_inbound_id"], "SYN-INBOUND-FAKE")
        client.submit_inbound.assert_called_once_with(
            source_e164="+5491100000001",
            destination_e164="+5491100000099",
            body="hola",
        )

    def test_happy_path_does_not_create_session_or_pedido(self) -> None:
        target = self._build_target()
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SYN-INBOUND-FAKE",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        # The route does not commit, rollback, flush, refresh, begin
        # or close the database session: it sits on the
        # request-level dependency.
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        # The route never instantiates a Session or Pedido model.
        self.session.add.assert_not_called()

    def test_happy_path_does_not_execute_business_queries_when_disabled(self) -> None:
        """The settings guard runs FIRST so the route cannot read or
        write any business query when the emulator action is
        disabled. The early guard short-circuits SQLAlchemy helpers
        so no business read is reached."""
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        # Use the default settings (no emulator enabled).
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings(),
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings(),
        )
        self._router_settings_patcher.start()
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
        ) as target_mock, patch.object(
            router_module,
            "build_emulator_control_client",
        ) as client_mock:
            response = self.client.post(
                "/admin/pilot/orders/emulator-bootstrap",
                json={
                    "cliente_id": 31,
                    "comercio_id": 1,
                    "message": "hola",
                },
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Emulator-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 400)
        # The route MUST NOT consult the bootstrap helpers when the
        # action is disabled, nor build the emulator client.
        target_mock.assert_not_called()
        client_mock.assert_not_called()

    def test_happy_path_does_not_echo_message_body(self) -> None:
        target = self._build_target()
        secret = "SECRET-OPERATOR-BODY-XYZ"
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SYN-INBOUND-FAKE",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post(
                body={
                    "cliente_id": 31,
                    "comercio_id": 1,
                    "message": secret,
                },
            )
        self.assertEqual(response.status_code, 200)
        # The wire payload is restricted to the synthetic inbound
        # identifier; the message body, the address fields and the
        # raw input are NEVER echoed.
        body_text = response.text
        for forbidden in (
            secret,
            "+5491100000001",
            "+5491100000099",
            "source_e164",
            "destination_e164",
            "control_token",
            "webhook_url",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body_text)
        body = response.json()
        self.assertEqual(set(body.keys()), {"synthetic_inbound_id"})
        self.assertEqual(body["synthetic_inbound_id"], "SYN-INBOUND-FAKE")

    def test_happy_path_never_replies_about_outbox_status(self) -> None:
        target = self._build_target()
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SYN-INBOUND-FAKE",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        # The bootstrap response is intentionally NF — the provider
        # worker is responsible for creating the active Session and
        # the draft Pedido.
        body = response.json()
        self.assertNotIn("status", body)
        self.assertNotIn("pedido", body)
        self.assertNotIn("session", body)
        self.assertNotIn("responses", body)

    def test_emulator_transport_failure_returns_generic_rejection(self) -> None:
        target = self._build_target()
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.side_effect = RuntimeError("boom")
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_routes_reject_form_urlencoded_submission(self) -> None:
        """The bootstrap JSON contract is preserved: a form-
        urlencoded body does NOT match the documented JSON
        contract so the route MUST reject the request and the
        bootstrap action stays invisible to non-JSON callers."""
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
        ) as target_mock:
            response = self.client.post(
                "/admin/pilot/orders/emulator-bootstrap",
                content="cliente_id=31&comercio_id=1&message=hola",
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Emulator-Test-Origin": "same-origin",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        self.assertIn(response.status_code, (400, 422))
        target_mock.assert_not_called()


class BootstrapRouteConfigurationTest(unittest.TestCase):
    """The bootstrap route enforces the explicit emulator
    configuration contract: ``TWILIO_PROVIDER_MODE=emulator``,
    ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=1`` and explicit emulator
    credentials. When any of those is missing the route returns
    the documented generic rejection without ever opening the
    database or invoking the emulator."""

    def _post(self, *, settings: Settings) -> Any:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=settings
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module, "load_settings", return_value=settings
        )
        self._router_settings_patcher.start()
        self._settings_patcher_obj = self._settings_patcher
        self._router_settings_patcher_obj = self._router_settings_patcher
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json={
                "cliente_id": 31,
                "comercio_id": 1,
                "message": "hola",
            },
            headers=headers,
        )

    def tearDown(self) -> None:
        self._settings_patcher_obj.stop()
        self._router_settings_patcher_obj.stop()
        self.app.dependency_overrides.clear()

    def test_real_mode_returns_generic_rejection(self) -> None:
        """When ``twilio_provider_mode == 'real'`` the bootstrap
        action is disabled even if the emulator credentials happen
        to be configured; the route never invokes a real
        provider."""
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "twilio_provider_mode": "real"}
        )
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(settings=settings)
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_isolated_disabled_returns_generic_rejection(self) -> None:
        """When ``commerce_isolated_outbound_enabled`` is off the
        bootstrap action is disabled even if the emulator
        credentials happen to be configured; the route never
        invokes the emulator."""
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "commerce_isolated_outbound_enabled": False}
        )
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(settings=settings)
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()

    def test_missing_emulator_credentials_returns_generic_rejection(self) -> None:
        """When emulator mode is enabled but the operator did not
        pin the credentials the bootstrap action is disabled; the
        route never invokes the emulator or the central
        dispatcher."""
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "twilio_emulator_account_sid": None}
        )
        with patch.object(
            router_module, "resolve_bootstrap_target"
        ) as target_mock:
            response = self._post(settings=settings)
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()


class BootstrapRouteNoDbWriteTest(unittest.TestCase):
    """The bootstrap route never writes a database record. The
    provider worker (not reached by the route) is the only
    component that creates the new Session and Pedido."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings_with_emulator_enabled(),
        )
        self._router_settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/emulator-bootstrap",
            json={
                "cliente_id": 31,
                "comercio_id": 1,
                "message": "hola",
            },
            headers=headers,
        )

    def test_route_never_calls_commit_via_active_session(self) -> None:
        """The active-session check is a read-only lookup. The
        route never queries the active session for deletion,
        mutation or closure."""
        from backend.services.admin_pilot_emulator_service import (
            EmulatorBootstrapTarget,
        )

        target = EmulatorBootstrapTarget(
            cliente_id=31,
            comercio_id=1,
            cliente_e164="+5491100000001",
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SYN-INBOUND-FAKE",
        )
        with patch.object(
            router_module,
            "resolve_bootstrap_target",
            return_value=target,
        ), patch.object(
            router_module,
            "load_active_session_for_comercio_cliente",
            return_value=None,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        # The route never instructs the session to terminate or
        # flush mid-call: those are the worker's responsibility.
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.add.assert_not_called()


class BootstrapRouteModuleSurfaceTest(unittest.TestCase):
    """The bootstrap route is the only new POST route exposed at
    ``/admin/pilot/orders`` prefix and the route's scope is
    limited to the documented JSON contract."""

    def setUp(self) -> None:
        self.app = _build_app()

    def test_bootstrap_route_is_post_only(self) -> None:
        for route in router_module.router.routes:
            path = getattr(route, "path", "")
            if path.endswith("/emulator-bootstrap"):
                methods = getattr(route, "methods", set())
                self.assertEqual(
                    methods,
                    {"POST"},
                    msg=(
                        "bootstrap route must be POST only, "
                        f"got {methods}"
                    ),
                )

    def test_bootstrap_request_schema_forbids_extra_fields(self) -> None:
        from pydantic import ValidationError

        from backend.routers.admin_pilot_orders import (
            EmulatorBootstrapRequest,
        )

        with self.assertRaises(ValidationError):
            EmulatorBootstrapRequest(
                cliente_id=31,
                comercio_id=1,
                message="hola",
                source_e164="+5491100000001",
            )

    def test_bootstrap_response_schema_forbids_extra_fields(self) -> None:
        from pydantic import ValidationError

        from backend.routers.admin_pilot_orders import (
            EmulatorBootstrapResponse,
        )

        with self.assertRaises(ValidationError):
            EmulatorBootstrapResponse(
                synthetic_inbound_id="SYN-FAKE",
                pedido_id=42,
            )


class BootstrapListTemplateTest(unittest.TestCase):
    """The list view renders the bootstrap form with the bounded
    controls and the documented button label. The form is
    server-rendered with the explicit ``action`` and the bounded
    selectors the JS handler uses."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[dependencies_module.get_session] = (
            self.session_override
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _get_list_response(self) -> str:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            from backend.services.pilot_order_operations_view_service import (
                OrderListView,
            )

            service_cls.return_value = SimpleNamespace(
                list_orders=MagicMock(
                    return_value=OrderListView(
                        rows=[],
                        total=0,
                        page=1,
                        page_size=25,
                    )
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_list_renders_bootstrap_form(self) -> None:
        body = self._get_list_response()
        self.assertIn("Iniciar inbound de cliente por Twilio Emulator", body)
        self.assertIn('action="/admin/pilot/orders/emulator-bootstrap"', body)
        self.assertIn("data-debug-bootstrap-form", body)
        self.assertIn("data-debug-bootstrap-cliente", body)
        self.assertIn("data-debug-bootstrap-comercio", body)
        self.assertIn("data-debug-bootstrap-textarea", body)
        self.assertIn("data-debug-bootstrap-submit", body)
        self.assertIn("data-debug-bootstrap-status", body)
        self.assertIn("data-debug-bootstrap-result", body)
        self.assertIn('maxlength="500"', body)

    def test_list_bootstrap_form_has_refresh_hint(self) -> None:
        body = self._get_list_response()
        self.assertIn("recargá el listado", body.lower())

    def test_list_bootstrap_form_uses_post(self) -> None:
        body = self._get_list_response()
        self.assertIn('method="post"', body)

    def test_list_bootstrap_form_only_renders_for_panel(self) -> None:
        # The unauthenticated case returns 401, not the form.
        response = self.client.get("/admin/pilot/orders")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Iniciar inbound de cliente", response.text)

    def test_bootstrap_handler_uses_json_content_type_and_origin_header(self) -> None:
        body = self._get_list_response()
        self.assertIn("data-debug-bootstrap-form", body)
        self.assertIn("X-Emulator-Test-Origin", body)
        self.assertIn("application/json", body)
        self.assertIn('credentials: "same-origin"', body)

    def test_bootstrap_handler_serializes_bounded_payload(self) -> None:
        body = self._get_list_response()
        self.assertIn("cliente_id", body)
        self.assertIn("comercio_id", body)
        self.assertIn("message", body)

    def test_bootstrap_handler_uses_positive_int_validation(self) -> None:
        body = self._get_list_response()
        self.assertIn("cliente_id y comercio_id", body)

    def test_bootstrap_handler_uses_generic_failure_message(self) -> None:
        body = self._get_list_response()
        self.assertIn("El Twilio Emulator rechazó el mensaje.", body)
        self.assertNotIn("fetch failed", body)
        self.assertNotIn("TypeError", body)
        self.assertNotIn("Error:", body)


class BootstrapServiceResolveTargetTest(unittest.TestCase):
    """Focused tests for :func:`resolve_bootstrap_target` covering
    the documented happy path and every documented rejection
    branch."""

    def setUp(self) -> None:
        import backend.services.admin_pilot_emulator_service as service_module

        self._service_module = service_module
        self._resolve_target = service_module.resolve_bootstrap_target
        self.session = MagicMock(name="DatabaseSession")

    def _stub_db_with_calls(self):
        """Wire a MagicMock session so chained ``execute(...).scalar_one_or_none()``
        returns the provided values in order."""
        calls = []

        def add_execute(return_value):
            mock = MagicMock()
            mock.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
                return_value
            )
            calls.append(mock)
            return mock

        return calls, add_execute

    def test_happy_path_returns_resolved_target(self) -> None:
        cliente = _stub_cliente()
        canal = _stub_canal()
        calls = [cliente, canal]
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = (
            calls
        )

        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module,
            "load_active_installation",
            return_value=_stub_installation(),
        ), patch.object(
            self._service_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ):
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.cliente_id, 31)
        self.assertEqual(result.comercio_id, 1)
        self.assertEqual(result.cliente_e164, "+5491100000001")
        self.assertEqual(result.canal_id, 5)
        self.assertEqual(result.canal_destination_e164, "+5491100000099")

    def test_non_positive_cliente_id_returns_none(self) -> None:
        result = self._resolve_target(self.session, cliente_id=0, comercio_id=1)
        self.assertIsNone(result)

    def test_non_positive_comercio_id_returns_none(self) -> None:
        result = self._resolve_target(
            self.session, cliente_id=31, comercio_id=0
        )
        self.assertIsNone(result)

    def test_missing_cliente_returns_none(self) -> None:
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            None
        )
        with patch.object(
            self._service_module, "resolve_cliente_e164"
        ) as cliente_mock:
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)
        cliente_mock.assert_not_called()

    def test_inactive_cliente_returns_none(self) -> None:
        cliente = _stub_cliente(activo=False)
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            cliente
        )
        with patch.object(
            self._service_module, "resolve_cliente_e164"
        ) as cliente_mock:
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)
        cliente_mock.assert_not_called()

    def test_invalid_cliente_e164_returns_none(self) -> None:
        cliente = _stub_cliente()
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            cliente
        )
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value=None,
        ), patch.object(
            self._service_module, "load_active_installation"
        ) as installation_mock:
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)
        installation_mock.assert_not_called()

    def test_missing_channel_returns_none(self) -> None:
        cliente = _stub_cliente()
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = [
            cliente,
            None,
        ]
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module, "load_active_installation"
        ) as installation_mock:
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)
        installation_mock.assert_not_called()

    def test_invalid_channel_destination_returns_none(self) -> None:
        cliente = _stub_cliente()
        canal = _stub_canal(destination="invalid")
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = [
            cliente,
            canal,
        ]
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module, "load_active_installation"
        ) as installation_mock:
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)
        installation_mock.assert_not_called()

    def test_inactive_installation_returns_none(self) -> None:
        cliente = _stub_cliente()
        canal = _stub_canal()
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = [
            cliente,
            canal,
        ]
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module,
            "load_active_installation",
            return_value=None,
        ):
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)

    def test_unavailable_commerce_returns_none(self) -> None:
        cliente = _stub_cliente()
        canal = _stub_canal()
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = [
            cliente,
            canal,
        ]
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module,
            "load_active_installation",
            return_value=_stub_installation(),
        ), patch.object(
            self._service_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.UNAVAILABLE,
        ):
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
            )
        self.assertIsNone(result)

    def test_resolve_target_does_not_mutate_session(self) -> None:
        cliente = _stub_cliente()
        canal = _stub_canal()
        session = MagicMock()
        session.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = [
            cliente,
            canal,
        ]
        with patch.object(
            self._service_module,
            "resolve_cliente_e164",
            return_value="+5491100000001",
        ), patch.object(
            self._service_module,
            "load_active_installation",
            return_value=_stub_installation(),
        ), patch.object(
            self._service_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ):
            result = self._resolve_target(
                session, cliente_id=31, comercio_id=1
        )
        self.assertIsNotNone(result)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()
        session.add.assert_not_called()


class BootstrapServiceActiveSessionTest(unittest.TestCase):
    """Focused tests for :func:`load_active_session_for_comercio_cliente`."""

    def setUp(self) -> None:
        from backend.services.admin_pilot_emulator_service import (
            load_active_session_for_comercio_cliente,
        )

        self._load_active_session = load_active_session_for_comercio_cliente
        self.session = MagicMock(name="DatabaseSession")

    def test_returns_active_session_when_present(self) -> None:
        session = _stub_active_session()
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            session
        )
        result = self._load_active_session(
            db, cliente_id=31, comercio_id=1
        )
        self.assertIs(result, session)

    def test_returns_none_when_no_active_session(self) -> None:
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            None
        )
        result = self._load_active_session(
            db, cliente_id=31, comercio_id=1
        )
        self.assertIsNone(result)

    def test_non_positive_ids_return_none(self) -> None:
        db = MagicMock()
        result = self._load_active_session(
            db, cliente_id=0, comercio_id=1
        )
        self.assertIsNone(result)
        db.execute.assert_not_called()

    def test_does_not_mutate_session(self) -> None:
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = (
            None
        )
        self._load_active_session(db, cliente_id=31, comercio_id=1)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.begin.assert_not_called()
        db.close.assert_not_called()
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
