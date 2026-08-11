"""Focused tests for the order-management API authorization boundary.

These tests cover the six acceptance scenarios from the
``secure-order-management-api`` change:

1. Server configuration absent or blank → ``503`` with a fixed
   non-sensitive detail; no database session or service work.
2. Header absent, blank, malformed, or wrong → ``401`` with a fixed
   non-sensitive detail; no database session or service work.
3. Header matching the configured token → existing behavior,
   including the ``PUT /pedidos/{pedido_id}/estado`` state
   transition, is preserved.
4. The Twilio inbound webhook and delivery callback remain outside
   the administrative-token boundary.
5. The dependency uses ``secrets.compare_digest`` on normalized
   string inputs.
6. The configured token, header, and request body are never logged.
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routers.pedido_productos as pedido_productos_router
import backend.routers.pedidos as pedidos_router
import backend.routers.twilio_delivery_callback as twilio_delivery_router
import backend.routers.twilio_webhook as twilio_webhook_router
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import (
    ADMIN_TOKEN_HEADER,
    get_session,
    require_admin_token,
)
from backend.models import EstadoPedido

CONFIGURED_TOKEN = "test-admin-token-please-do-not-leak"


def _settings(token: str | None = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(
        **{**base.__dict__, "order_management_admin_token": token}
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(pedidos_router.router)
    app.include_router(pedido_productos_router.router)
    return app


class _SessionOverride:
    """Explicit ``get_session`` override with a no-argument signature.

    FastAPI introspects the override callable to detect required
    parameters; ``MagicMock`` exposes ``__call__(*args, **kwargs)``,
    which the framework treats as keyword arguments and rejects
    with ``422``. This helper exposes an explicit empty
    ``__call__(self)`` so FastAPI accepts it as a dependency with
    no required parameters, while still allowing tests to assert
    invocation counts.
    """

    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.call_count = 0
        self.call_args_list: list[tuple[object, ...]] = []

    def __call__(self) -> object:
        self.call_count += 1
        self.call_args_list.append(())
        return self._return_value

    def assert_not_called(self) -> None:
        if self.call_count != 0:
            raise AssertionError(
                f"override was called {self.call_count} time(s)"
            )

    def assert_called_once(self) -> None:
        if self.call_count != 1:
            raise AssertionError(
                f"override was called {self.call_count} time(s), expected 1"
            )


class OrderManagementApiSecurityConfigMissingTest(unittest.TestCase):
    """Server token absent or blank returns ``503`` and touches no
    database session or service."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.pedidos_service = MagicMock(name="PedidoService")
        self.pedido_productos_service = MagicMock(name="PedidoProductoService")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings"
        )
        load_settings_mock = self._settings_patcher.start()
        load_settings_mock.return_value = _settings(token=None)
        self._pedidos_service_patcher = patch.object(
            pedidos_router, "PedidoService", self.pedidos_service
        )
        self._pedidos_service_patcher.start()
        self._pedido_productos_service_patcher = patch.object(
            pedido_productos_router,
            "PedidoProductoService",
            self.pedido_productos_service,
        )
        self._pedido_productos_service_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._pedidos_service_patcher.stop()
        self._pedido_productos_service_patcher.stop()
        self.app.dependency_overrides.clear()

    def _assert_no_business_work(self) -> None:
        self.session_override.assert_not_called()
        self.pedidos_service.assert_not_called()
        self.pedido_productos_service.assert_not_called()

    def test_config_absent_returns_503_for_pedidos_listing(self) -> None:
        response = self.client.get(
            "/pedidos/7",
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self._assert_no_business_work()

    def test_config_blank_returns_503_for_pedido_creation(self) -> None:
        with patch.object(
            dependencies_module, "load_settings"
        ) as load_settings_mock:
            load_settings_mock.return_value = _settings(token="   ")
            response = self.client.post(
                "/pedidos",
                json={"id_session": 1},
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self._assert_no_business_work()

    def test_config_absent_returns_503_for_pedido_productos(self) -> None:
        response = self.client.get(
            "/pedidos/7/productos",
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self._assert_no_business_work()


class OrderManagementApiSecurityUnauthorizedTest(unittest.TestCase):
    """Client credential absent, blank, malformed, or wrong returns
    ``401`` and touches no database session or service."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.pedidos_service = MagicMock(name="PedidoService")
        self.pedido_productos_service = MagicMock(name="PedidoProductoService")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()
        self._pedidos_service_patcher = patch.object(
            pedidos_router, "PedidoService", self.pedidos_service
        )
        self._pedidos_service_patcher.start()
        self._pedido_productos_service_patcher = patch.object(
            pedido_productos_router,
            "PedidoProductoService",
            self.pedido_productos_service,
        )
        self._pedido_productos_service_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._pedidos_service_patcher.stop()
        self._pedido_productos_service_patcher.stop()
        self.app.dependency_overrides.clear()

    def _assert_401(self, response) -> None:
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )
        self.session_override.assert_not_called()
        self.pedidos_service.assert_not_called()
        self.pedido_productos_service.assert_not_called()

    def test_header_absent_returns_401(self) -> None:
        response = self.client.get("/pedidos/7")
        self._assert_401(response)

    def test_header_blank_returns_401(self) -> None:
        response = self.client.get(
            "/pedidos/7",
            headers={ADMIN_TOKEN_HEADER: "   "},
        )
        self._assert_401(response)

    def test_header_empty_returns_401(self) -> None:
        response = self.client.get(
            "/pedidos/7",
            headers={ADMIN_TOKEN_HEADER: ""},
        )
        self._assert_401(response)

    def test_header_wrong_returns_401(self) -> None:
        response = self.client.get(
            "/pedidos/7",
            headers={ADMIN_TOKEN_HEADER: "definitely-not-the-token"},
        )
        self._assert_401(response)

    def test_header_wrong_for_pedido_productos_returns_401(self) -> None:
        response = self.client.get(
            "/pedidos-productos/3",
            headers={ADMIN_TOKEN_HEADER: "also-wrong"},
        )
        self._assert_401(response)

    def test_denial_does_not_invoke_session_or_service(self) -> None:
        response = self.client.get("/pedidos/7")
        self._assert_401(response)


class OrderManagementApiSecurityAuthorizedTest(unittest.TestCase):
    """Matching token preserves existing behavior."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_get_pedido_with_matching_token_returns_service_payload(self) -> None:
        pedido = MagicMock(name="Pedido")
        pedido.id = 7
        pedido.id_session = 1
        pedido.id_medio_pago = None
        pedido.id_metodo_entrega = None
        pedido.datetime_entrega_programada = None
        pedido.estado_pedido = EstadoPedido.BORRADOR
        pedido.fecha_alta = "2026-08-11T12:00:00"
        pedido.fecha_ultima_modificacion = "2026-08-11T12:00:00"

        with patch.object(
            pedidos_router, "PedidoService"
        ) as service_cls:
            service = MagicMock(name="PedidoService")
            service_cls.return_value = service
            service.get_by_id.return_value = pedido

            response = self.client.get(
                "/pedidos/7",
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 7)
        service.get_by_id.assert_called_once_with(7)

    def test_state_transition_with_matching_token_uses_service(self) -> None:
        pedido = MagicMock(name="Pedido")
        pedido.id = 7
        pedido.id_session = 1
        pedido.id_medio_pago = None
        pedido.id_metodo_entrega = None
        pedido.datetime_entrega_programada = None
        pedido.estado_pedido = EstadoPedido.INGRESADO
        pedido.fecha_alta = "2026-08-11T12:00:00"
        pedido.fecha_ultima_modificacion = "2026-08-11T12:00:00"

        with patch.object(
            pedidos_router, "PedidoService"
        ) as service_cls:
            service = MagicMock(name="PedidoService")
            service_cls.return_value = service
            service.cambiar_estado.return_value = pedido

            response = self.client.put(
                "/pedidos/7/estado",
                json={"estado_pedido": "ingresado"},
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estado_pedido"], "ingresado")
        service.cambiar_estado.assert_called_once()
        called_args = service.cambiar_estado.call_args.args
        self.assertEqual(called_args[0], 7)
        self.assertEqual(called_args[1], EstadoPedido.INGRESADO)


class OrderManagementApiSecurityConstantTimeTest(unittest.TestCase):
    """The dependency delegates to ``secrets.compare_digest`` with
    normalized string inputs."""

    def test_compare_digest_called_with_normalized_strings(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ), patch.object(
            dependencies_module.secrets, "compare_digest", return_value=True
        ) as compare_mock:
            require_admin_token(
                x_admin_token=f"  {CONFIGURED_TOKEN}  ",
            )

        compare_mock.assert_called_once_with(
            CONFIGURED_TOKEN, CONFIGURED_TOKEN
        )


class OrderManagementApiSecurityObservabilityTest(unittest.TestCase):
    """The dependency must not log the configured token, the
    presented header, the raw request body, or the header name."""

    def test_dependency_does_not_emit_log_records(self) -> None:
        records: list[str] = []
        logger = logging.getLogger("backend.dependencies")
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            logger.debug(
                "request body marker - must not appear in logs"
            )
            self.assertIn(
                "request body marker - must not appear in logs",
                records,
                msg="log handler wiring sanity check failed",
            )
            records.clear()
            with patch.object(
                dependencies_module, "load_settings", return_value=_settings()
            ):
                try:
                    require_admin_token(x_admin_token=CONFIGURED_TOKEN)
                except HTTPException:
                    self.fail("matching credential must not raise")
                for bad in ("definitely-wrong", " ", "", None):
                    with self.subTest(bad=bad):
                        with self.assertRaises(HTTPException):
                            require_admin_token(x_admin_token=bad)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        joined = "\n".join(records)
        self.assertNotIn(CONFIGURED_TOKEN, joined)
        self.assertNotIn("definitely-wrong", joined)
        self.assertNotIn(ADMIN_TOKEN_HEADER, joined)
        self.assertNotIn(
            "request body marker - must not appear in logs", joined
        )


class OrderManagementApiSecurityTwilioBoundaryTest(unittest.TestCase):
    """Twilio inbound webhook and delivery callback stay outside the
    administrative-token boundary."""

    @staticmethod
    def _collect_dep_calls(router) -> list:
        calls: list = []
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for dep in route.dependant.dependencies:
                calls.append(dep.call)
        return calls

    def test_twilio_webhook_router_does_not_use_require_admin_token(self) -> None:
        calls = self._collect_dep_calls(twilio_webhook_router.router)
        self.assertNotIn(
            require_admin_token,
            calls,
            msg=(
                "Twilio inbound webhook must not depend on the "
                "administrative-token dependency"
            ),
        )

    def test_twilio_delivery_callback_does_not_use_require_admin_token(self) -> None:
        calls = self._collect_dep_calls(twilio_delivery_router.router)
        self.assertNotIn(
            require_admin_token,
            calls,
            msg=(
                "Twilio delivery callback must not depend on the "
                "administrative-token dependency"
            ),
        )

    def test_pedidos_router_routes_carry_require_admin_token(self) -> None:
        calls = self._collect_dep_calls(pedidos_router.router)
        self.assertIn(require_admin_token, calls)

    def test_pedido_productos_router_routes_carry_require_admin_token(self) -> None:
        calls = self._collect_dep_calls(pedido_productos_router.router)
        self.assertIn(require_admin_token, calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
