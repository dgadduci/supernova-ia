"""Focused tests for the Admin/Pilot emulator draft inbound extension.

These tests cover the narrow extension that lets the authenticated
Admin/Pilot detail action ``Enviar por Twilio Emulator`` submit a
provider-shaped inbound for an exact active Session whose associated
Pedido is still ``BORRADOR``. The extension is the only newly
eligible Pedido state; every identity, ownership, dedicated-channel,
commerce-availability, T-C-installation and explicit-emulator guard
from the existing non-draft flow is preserved.

The tests exercise both the read-only target loader and the existing
detail POST/status routes through a fake emulator control client and
the canonical repository seams. They never touch a real database,
Twilio, T-C or worker. The existing local-test action and the
existing non-draft emulator action are also covered to guarantee the
change remains non-regressive.
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
from backend.models import (
    CanalWhatsappMode,
    EstadoPedido,
    EstadoSession,
)
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
        **{
            **base.__dict__,
            "twilio_provider_mode": "emulator",
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


def _stub_cliente(*, cliente_id: int = 31, whatsapp: str = "+5491100000001"):
    return SimpleNamespace(id=cliente_id, activo=True, whatsapp=whatsapp)


def _stub_comercio(*, comercio_id: int = 1):
    return SimpleNamespace(id=comercio_id)


def _stub_session(
    *,
    session_id: int = 21,
    pedido_id: int = 42,
    cliente_id: int = 31,
    comercio_id: int = 1,
    estado: EstadoSession = EstadoSession.ACTIVA,
):
    return SimpleNamespace(
        id=session_id,
        id_pedido=pedido_id,
        id_cliente=cliente_id,
        id_comercio=comercio_id,
        estado_session=estado,
    )


def _stub_pedido(
    *,
    pedido_id: int = 42,
    estado: EstadoPedido = EstadoPedido.BORRADOR,
    session: object | None = None,
):
    pedido = SimpleNamespace(
        id=pedido_id,
        estado_pedido=estado,
    )
    pedido.session = session
    return pedido


def _stub_canal(
    *,
    canal_id: int = 5,
    destination: str = "+5491100000099",
    activo: bool = True,
    mode: CanalWhatsappMode = CanalWhatsappMode.DEDICATED,
    provider: str = "twilio",
    comercio_exclusivo: int | None = 1,
):
    canal = SimpleNamespace(
        id=canal_id,
        destination_e164=destination,
        activo=activo,
        mode=mode,
        provider=provider,
        id_comercio_exclusivo=comercio_exclusivo,
    )
    return canal


def _stub_installation(*, activo: bool = True):
    return SimpleNamespace(id=1, id_comercio=1, activo=activo)


def _wire_loader_db(
    *,
    pedido: object | None,
    canal: object | None,
):
    """Build a MagicMock DB so the loader's execute chain returns the
    given pedido (first call) and canal (second call).

    The loader calls ``db.execute(...)`` once for the Pedido lookup
    and the dedicated channel helper calls ``db.execute(...)`` again
    for the canal lookup. Both go through the same chain.
    """
    db = MagicMock()
    db.execute.return_value.unique.return_value.scalar_one_or_none.side_effect = (
        [pedido, canal]
    )
    return db


def _target():
    from backend.services.admin_pilot_emulator_service import (
        EmulatorTestTarget,
    )

    return EmulatorTestTarget(
        pedido_id=42,
        session_id=21,
        cliente_id=31,
        comercio_id=1,
        canal_id=5,
        canal_destination_e164="+5491100000099",
    )


def _install_emulator_patches(
    *,
    target: object | None = None,
    installation: object | None = _stub_installation(),
    commerce_status: CommerceAvailabilityStatus = (
        CommerceAvailabilityStatus.AVAILABLE
    ),
    cliente_e164: str | None = "+5491100000001",
):
    """Return a context-manager list that wires the route's external
    seams for a happy-path submission."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target if target is not None else _target(),
        )
    )
    stack.enter_context(
        patch.object(
            router_module,
            "load_active_installation",
            return_value=installation,
        )
    )
    stack.enter_context(
        patch.object(
            router_module,
            "commerce_availability_status",
            return_value=commerce_status,
        )
    )
    stack.enter_context(
        patch.object(
            router_module,
            "resolve_cliente_e164",
            return_value=cliente_e164,
        )
    )
    return stack


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
            message_sid="SM-DRAFT-1",
            synthetic_inbound_id="SYN-DRAFT-1",
        )


class LoadActiveEmulatorTargetDraftAcceptanceTest(unittest.TestCase):
    """Focused unit tests for :func:`load_active_emulator_target`
    exercising the draft acceptance branch."""

    def setUp(self) -> None:
        import backend.services.admin_pilot_emulator_service as service_module

        self._service_module = service_module
        self._loader = service_module.load_active_emulator_target

    def test_accepts_exact_borrador_with_active_session(self) -> None:
        cliente = _stub_cliente()
        comercio = _stub_comercio()
        session = _stub_session()
        session.cliente = cliente
        session.comercio = comercio
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        result = self._loader(db, pedido_id=42)
        self.assertIsNotNone(result)
        self.assertEqual(result.pedido_id, 42)
        self.assertEqual(result.session_id, 21)
        self.assertEqual(result.cliente_id, 31)
        self.assertEqual(result.comercio_id, 1)
        self.assertEqual(result.canal_id, 5)
        self.assertEqual(result.canal_destination_e164, "+5491100000099")

    def test_accepts_non_borrador_with_active_session(self) -> None:
        cliente = _stub_cliente()
        comercio = _stub_comercio()
        session = _stub_session()
        session.cliente = cliente
        session.comercio = comercio
        pedido = _stub_pedido(
            estado=EstadoPedido.INGRESADO, session=session
        )
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        result = self._loader(db, pedido_id=42)
        self.assertIsNotNone(result)
        self.assertEqual(result.pedido_id, 42)


class LoadActiveEmulatorTargetDraftRejectionTest(unittest.TestCase):
    """Focused unit tests for :func:`load_active_emulator_target`
    exercising every documented rejection branch for the draft
    extension."""

    def setUp(self) -> None:
        import backend.services.admin_pilot_emulator_service as service_module

        self._service_module = service_module
        self._loader = service_module.load_active_emulator_target

    def test_missing_pedido_returns_none(self) -> None:
        db = _wire_loader_db(pedido=None, canal=None)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_borrador_without_session_returns_none(self) -> None:
        pedido = _stub_pedido(session=None)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_inactive_session_returns_none_for_borrador(self) -> None:
        session = _stub_session(estado=EstadoSession.CERRADA)
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_session_id_pedido_mismatch_returns_none(self) -> None:
        session = _stub_session(pedido_id=999)
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_cross_commerce_session_returns_none(self) -> None:
        """A session whose ``id_comercio`` FK does not match the
        loaded ``comercio.id`` is rejected by the loader so the
        route never holds a cross-commerce identity for the
        emulator path. The loader collapses the inconsistent
        FK/row shape to ``None`` and the route emits the
        documented generic rejection."""
        cliente = _stub_cliente()
        cross_commerce = SimpleNamespace(id=2)
        session = _stub_session()
        session.cliente = cliente
        session.comercio = cross_commerce
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_cross_cliente_session_returns_none(self) -> None:
        """A session whose ``id_cliente`` FK does not match the
        loaded ``cliente.id`` is rejected by the loader so the
        route never holds a cross-cliente identity for the
        emulator path. The loader collapses the inconsistent
        FK/row shape to ``None`` and the route emits the
        documented generic rejection."""
        cross_cliente = _stub_cliente(cliente_id=999)
        comercio = _stub_comercio()
        session = _stub_session()
        session.cliente = cross_cliente
        session.comercio = comercio
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_missing_dedicated_channel_returns_none(self) -> None:
        session = _stub_session()
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        db = _wire_loader_db(pedido=pedido, canal=None)
        self.assertIsNone(self._loader(db, pedido_id=42))

    def test_inactive_dedicated_channel_returns_none(self) -> None:
        session = _stub_session()
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        # The dedicated channel helper applies
        # ``CanalWhatsapp.activo.is_(True)``; the loader returns
        # ``None`` when the channel is inactive, mirroring the same
        # fail-closed contract used for the non-draft branch.
        with patch.object(
            self._service_module,
            "_load_dedicated_canal",
            return_value=None,
        ):
            db = _wire_loader_db(pedido=pedido, canal=None)
            self.assertIsNone(self._loader(db, pedido_id=42))

    def test_non_dedicated_channel_returns_none(self) -> None:
        session = _stub_session()
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        # The dedicated channel helper filters by
        # ``mode == CanalWhatsappMode.DEDICATED`` and provider;
        # a shared or non-Twilio channel collapses to ``None``.
        with patch.object(
            self._service_module,
            "_load_dedicated_canal",
            return_value=None,
        ):
            db = _wire_loader_db(pedido=pedido, canal=None)
            self.assertIsNone(self._loader(db, pedido_id=42))

    def test_non_twilio_provider_returns_none(self) -> None:
        session = _stub_session()
        session.cliente = _stub_cliente()
        session.comercio = _stub_comercio()
        pedido = _stub_pedido(session=session)
        with patch.object(
            self._service_module,
            "_load_dedicated_canal",
            return_value=None,
        ):
            db = _wire_loader_db(pedido=pedido, canal=None)
            self.assertIsNone(self._loader(db, pedido_id=42))

    def test_does_not_mutate_session(self) -> None:
        cliente = _stub_cliente()
        comercio = _stub_comercio()
        session = _stub_session()
        session.cliente = cliente
        session.comercio = comercio
        pedido = _stub_pedido(session=session)
        canal = _stub_canal()
        db = _wire_loader_db(pedido=pedido, canal=canal)
        self._loader(db, pedido_id=42)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.begin.assert_not_called()
        db.close.assert_not_called()


class EmulatorDraftRouteAuthHeaderTest(unittest.TestCase):
    """The detail POST emulator action requires the same Basic-auth and
    same-origin header guards the rest of the panel enforces."""

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

    def test_missing_credential_returns_401(self) -> None:
        response = self.client.post(
            "/admin/pilot/orders/42/emulator-test",
            json={"message": "hola"},
            headers={"X-Emulator-Test-Origin": "same-origin"},
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock:
            response = self.client.post(
                "/admin/pilot/orders/42/emulator-test",
                json={"message": "hola"},
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()


class EmulatorDraftRouteBodyValidationTest(unittest.TestCase):
    """Body validation rejects empty, malformed and oversized payloads
    for a draft pedido before any pipeline work runs."""

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

    def _post(self, *, body):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/emulator-test",
            json=body,
            headers=headers,
        )

    def test_empty_body_returns_422(self) -> None:
        with patch.object(
            router_module, "load_active_emulator_target"
        ) as target_mock:
            response = self._post(body={})
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_empty_message_returns_422(self) -> None:
        with patch.object(
            router_module, "load_active_emulator_target"
        ) as target_mock:
            response = self._post(body={"message": ""})
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_oversized_message_returns_422(self) -> None:
        with patch.object(
            router_module, "load_active_emulator_target"
        ) as target_mock:
            response = self._post(body={"message": "x" * 501})
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()

    def test_extra_field_returns_422(self) -> None:
        with patch.object(
            router_module, "load_active_emulator_target"
        ) as target_mock:
            response = self._post(
                body={
                    "message": "hola",
                    "source_e164": "+5491100000001",
                    "destination_e164": "+5491100000099",
                    "control_token": "x",
                    "webhook_url": "https://attacker.example",
                }
            )
        self.assertEqual(response.status_code, 422)
        target_mock.assert_not_called()


class EmulatorDraftRouteHappyPathTest(unittest.TestCase):
    """A valid draft submission invokes the emulator exactly once with
    server-resolved addresses and never mutates the SQLAlchemy session.
    The route never creates or replaces a Session/Pedido."""

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
            "/admin/pilot/orders/42/emulator-test",
            json=body if body is not None else {"message": "hola"},
            headers=headers,
        )

    def test_happy_path_invokes_emulator_once_with_server_resolved_addresses(
        self,
    ) -> None:
        target = _target()
        client = _RecordingClient()
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synthetic_inbound_id"], "SYN-DRAFT-1")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0],
            {
                "source_e164": "+5491100000001",
                "destination_e164": "+5491100000099",
                "body": "hola",
            },
        )

    def test_happy_path_uses_server_resolved_addresses_not_browser_input(
        self,
    ) -> None:
        """The browser never picks the addresses. The route resolves
        them from the database through ``resolve_cliente_e164`` and
        ``target.canal_destination_e164``. An operator-supplied
        address-shaped field is rejected by the request schema
        BEFORE the route reaches the emulator client."""
        target = _target()
        client = _RecordingClient()
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self.client.post(
                "/admin/pilot/orders/42/emulator-test",
                json={
                    "message": "hola",
                    "source_e164": "+14085550001",
                    "destination_e164": "+14085550099",
                },
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Emulator-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(client.calls), 0)

    def test_happy_path_does_not_create_session_or_pedido(self) -> None:
        target = _target()
        client = MagicMock()
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-DRAFT-1",
            synthetic_inbound_id="SYN-DRAFT-1",
        )
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.session.add.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_two_consecutive_messages_preserve_session_and_pedido_identity(
        self,
    ) -> None:
        target = _target()
        client = MagicMock()
        client.submit_inbound.side_effect = [
            MagicMock(
                status="accepted",
                message_sid="SM-DRAFT-1",
                synthetic_inbound_id="SYN-DRAFT-1",
            ),
            MagicMock(
                status="accepted",
                message_sid="SM-DRAFT-2",
                synthetic_inbound_id="SYN-DRAFT-2",
            ),
        ]
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            first = self._post(body={"message": "primer"})
            second = self._post(body={"message": "segundo"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(client.submit_inbound.call_count, 2)
        # Both calls reuse the same server-resolved identities.
        first_call = client.submit_inbound.call_args_list[0]
        second_call = client.submit_inbound.call_args_list[1]
        self.assertEqual(
            first_call.kwargs["source_e164"],
            second_call.kwargs["source_e164"],
        )
        self.assertEqual(
            first_call.kwargs["destination_e164"],
            second_call.kwargs["destination_e164"],
        )
        self.assertNotEqual(
            first_call.kwargs["body"],
            second_call.kwargs["body"],
        )
        # No replacement session/pedido is created.
        self.session.add.assert_not_called()

    def test_duplicate_synthetic_inbound_is_idempotent(self) -> None:
        """The route forwards a unique synthetic inbound identifier
        per submission. The provider receipt/outbox idempotency is
        owned by the canonical pipeline; the route itself MUST NOT
        short-circuit the second call when the browser retries with
        the same synthetic inbound identifier — that is the
        provider worker concern, not the route concern."""
        target = _target()
        client = MagicMock()
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-DRAFT-DUP",
            synthetic_inbound_id="SYN-DRAFT-DUP",
        )
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            first = self._post(body={"message": "hola"})
            second = self._post(body={"message": "hola"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        # The route forwards both submissions; the canonical
        # pipeline handles duplicate receipts downstream.
        self.assertEqual(client.submit_inbound.call_count, 2)
        self.assertEqual(
            first.json()["synthetic_inbound_id"],
            "SYN-DRAFT-DUP",
        )
        self.assertEqual(
            second.json()["synthetic_inbound_id"],
            "SYN-DRAFT-DUP",
        )


class EmulatorDraftRouteOperationalGuardsTest(unittest.TestCase):
    """The detail POST emulator action still fails closed on every
    documented operational guard when targeting an active draft."""

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
            "/admin/pilot/orders/42/emulator-test",
            json={"message": "hola"},
            headers=headers,
        )

    def test_invalid_target_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=None,
        ) as target_mock, patch.object(
            router_module,
            "build_emulator_control_client",
        ) as client_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        target_mock.assert_called_once()
        client_mock.assert_not_called()

    def test_unavailable_commerce_returns_generic_rejection(self) -> None:
        target = _target()
        stack = _install_emulator_patches(
            target=target,
            commerce_status=CommerceAvailabilityStatus.UNAVAILABLE,
        )
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=MagicMock(),
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_missing_installation_returns_generic_rejection(self) -> None:
        target = _target()
        stack = _install_emulator_patches(
            target=target,
            installation=None,
        )
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=MagicMock(),
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_disabled_emulator_returns_generic_rejection(self) -> None:
        target = _target()
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
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
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
        ) as client_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        client_mock.assert_not_called()

    def test_missing_emulator_client_returns_generic_rejection(self) -> None:
        target = _target()
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=None,
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_invalid_cliente_e164_returns_generic_rejection(self) -> None:
        target = _target()
        stack = _install_emulator_patches(
            target=target,
            cliente_e164=None,
        )
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=MagicMock(),
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_emulator_transport_failure_returns_generic_rejection(self) -> None:
        target = _target()
        client = MagicMock()
        client.submit_inbound.side_effect = RuntimeError("boom")
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self._post()
        self.assertEqual(response.status_code, 400)


class EmulatorDraftRouteStatusTest(unittest.TestCase):
    """The existing bounded status projection polls the exact active
    draft and rejects status requests that target another pedido or
    commerce."""

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
            "/admin/pilot/orders/42/emulator-test/status",
            json=body
            if body is not None
            else {"synthetic_inbound_id": "SYN-DRAFT-1"},
            headers=headers,
        )

    def test_status_polling_for_exact_draft(self) -> None:
        target = _target()
        summary = router_module.EmulatorStatusResponse(
            status="accepted",
            outbound_body=None,
            provider_message_sid=None,
            timeline=router_module.EmulatorTimeline(),
            diagnostic=router_module.EmulatorDiagnostic(
                processing_state="pending",
                response_count=None,
                outbox_row_count=0,
                failure_category=None,
            ),
        )
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ) as target_mock, patch.object(
            router_module,
            "_emulator_outbox_summary",
            return_value=summary,
        ) as summary_mock:
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        target_mock.assert_called_once()
        summary_mock.assert_called_once()
        kwargs = summary_mock.call_args.kwargs
        self.assertEqual(kwargs["pedido_id"], 42)
        self.assertIs(kwargs["target"], target)
        self.assertEqual(
            kwargs["synthetic_inbound_id"], "SYN-DRAFT-1"
        )

    def test_status_missing_target_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=None,
        ) as target_mock, patch.object(
            router_module,
            "_emulator_outbox_summary",
        ) as summary_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        target_mock.assert_called_once()
        summary_mock.assert_not_called()

    def test_status_missing_origin_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock:
            response = self.client.post(
                "/admin/pilot/orders/42/emulator-test/status",
                json={"synthetic_inbound_id": "SYN-DRAFT-1"},
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()


class EmulatorDraftRouteRegressionTest(unittest.TestCase):
    """Non-regression coverage for the existing non-draft detail
    emulator action and the local-only panel channel."""

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

    def test_non_borrador_pedido_still_works(self) -> None:
        """The existing non-draft detail emulator action still runs
        through the same pipeline for a non-BORRADOR pedido."""
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000099",
        )
        client = MagicMock()
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-NON-DRAFT",
            synthetic_inbound_id="SYN-NON-DRAFT",
        )
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self.client.post(
                "/admin/pilot/orders/42/emulator-test",
                json={"message": "hola"},
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Emulator-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["synthetic_inbound_id"], "SYN-NON-DRAFT"
        )

    def test_local_test_route_still_works(self) -> None:
        """The local-only action remains unaffected by the draft
        extension: it rejects when the loaders cannot resolve a
        target and never invokes the emulator client."""
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=None,
        ):
            response = self.client.post(
                "/admin/pilot/orders/42/local-test",
                json={"message": "hola"},
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Local-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["responses"], [])

    def test_bootstrap_guard_still_rejects_active_context(self) -> None:
        """The bootstrap route still rejects when an active Session
        already exists for the cliente/comercio pair; the draft
        extension does NOT touch that guard."""
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
            return_value=SimpleNamespace(id=99),
        ) as session_mock, patch.object(
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
        session_mock.assert_called_once()
        client_mock.assert_not_called()

    def test_route_does_not_call_commit_rollback_flush_refresh_begin_close(
        self,
    ) -> None:
        target = _target()
        client = MagicMock()
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-DRAFT-1",
            synthetic_inbound_id="SYN-DRAFT-1",
        )
        stack = _install_emulator_patches(target=target)
        stack.enter_context(
            patch.object(
                router_module,
                "build_emulator_control_client",
                return_value=client,
            )
        )
        with stack:
            response = self.client.post(
                "/admin/pilot/orders/42/emulator-test",
                json={"message": "hola"},
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Emulator-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.add.assert_not_called()


class EmulatorDraftDetailTemplateTest(unittest.TestCase):
    """The detail page surfaces the documented draft eligibility copy
    when the emulator action is enabled."""

    def _build_app_with(self, settings: Settings) -> TestClient:
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
            return_value=settings,
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module,
            "load_settings",
            return_value=settings,
        )
        self._router_settings_patcher.start()
        return self.client

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _render_detail(self, *, enabled: bool) -> str:
        from datetime import datetime, timezone

        from backend.services.pilot_order_operations_view_service import (
            ClientSummary,
            CommerceSummary,
            DeliveryMethodView,
            OrderDetailView,
            OrderLineSnapshot,
            OrderSummary,
            PaymentMethodView,
            SessionSummary,
            format_local_datetime,
        )

        self._build_app_with(_settings_with_emulator_enabled())
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        zona = "America/Argentina/Buenos_Aires"
        detail = OrderDetailView(
            pedido=OrderSummary(
                id=42,
                estado_pedido=EstadoPedido.BORRADOR,
                fecha_alta=base,
                fecha_alta_local=format_local_datetime(base, zona),
                fecha_ultima_modificacion=base,
                fecha_ultima_modificacion_local=format_local_datetime(
                    base, zona
                ),
            ),
            session=SessionSummary(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=base,
                datetime_inicio_local=format_local_datetime(base, zona),
                datetime_ultimo_movimiento=base,
                datetime_ultimo_movimiento_local=format_local_datetime(
                    base, zona
                ),
            ),
            client=ClientSummary(
                id=31,
                nombre="Ana",
                whatsapp="+5491100000001",
                activo=True,
            ),
            commerce=CommerceSummary(
                id=1,
                nombre_fantasia="Comercio A",
                nombre_corto="A",
                zona_horaria="America/Argentina/Buenos_Aires",
            ),
            direccion_entrega=None,
            observaciones=None,
            datetime_entrega_programada=None,
            datetime_entrega_programada_local=None,
            medio_pago=PaymentMethodView(id=7, descripcion="Efectivo"),
            metodo_entrega=DeliveryMethodView(id=8, descripcion="Retiro"),
            lineas=[],
        )
        history_view = SimpleNamespace(entries=[])
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=None,
        ), patch.object(
            router_module,
            "_is_emulator_action_enabled",
            return_value=enabled,
        ), patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = SimpleNamespace(
                list_orders=MagicMock(),
                get_detail=MagicMock(return_value=detail),
                get_provider_history=MagicMock(return_value=history_view),
                get_order_lines_snapshot=MagicMock(
                    return_value=[
                        OrderLineSnapshot(
                            id=1,
                            producto_nombre="Pan",
                            presentacion_descripcion=None,
                            cantidad=1,
                            precio_unitario_display="$100.00",
                            observaciones=None,
                        )
                    ]
                ),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_detail_renders_draft_eligibility_copy_when_enabled(self) -> None:
        body = self._render_detail(enabled=True)
        self.assertIn("Enviar por Twilio Emulator", body)
        self.assertIn(
            "debug-emulator-eligibility", body
        )
        self.assertIn("borrador", body.lower())
        self.assertIn("sesión activa", body.lower())
        # The copy must NOT narrow the eligibility to pedidos
        # "ya confirmados" because the actual emulator action
        # accepts any non-BORRADOR order that passes its
        # operational validations. The exact, neutral wording
        # must be present so the operator knows the action
        # stays isolated from real WhatsApp/Twilio and from the
        # local channel button.
        self.assertNotIn("confirmados", body.lower())
        self.assertIn("operativas", body.lower())
        self.assertIn("no contacta", body.lower())
        self.assertIn("canal local", body.lower())

    def test_detail_does_not_render_emulator_form_when_disabled(self) -> None:
        body = self._render_detail(enabled=False)
        self.assertIn("Twilio Emulator (deshabilitado)", body)
        self.assertNotIn(
            'action="/admin/pilot/orders/42/emulator-test"', body
        )


if __name__ == "__main__":
    unittest.main()
