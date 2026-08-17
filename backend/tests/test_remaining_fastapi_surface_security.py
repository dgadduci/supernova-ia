"""Focused tests for the administrative-token boundary extension.

These tests cover the six acceptance scenarios from the
``secure-remaining-fastapi-surface`` change:

1. Route inventory is derived from ``backend.main.app.routes`` (no
   static router or module lists): every APIRoute actually
   registered by the application is classified either as exempt
   (no ``require_admin_token``) or administrative (must require
   ``require_admin_token``). A new unprotected route surfaces as a
   failed inventory test that names the unclassified path.
2. The only exempt routes are ``/health``,
   ``/webhooks/twilio/whatsapp/inbound`` and
   ``/webhooks/twilio/whatsapp/status``; each of those three
   APIRoutes does not evaluate ``require_admin_token`` in its
   FastAPI dependency metadata.
3. Server configuration absent or blank returns ``503`` for
   representative administrative routers with no session or service
   work, including ``incoming_messages`` and
   ``admin_product_embeddings``.
4. Header absent, blank, or wrong returns ``401`` for representative
   administrative routers with no session or service work, including
   ``incoming_messages`` and ``admin_product_embeddings``.
5. Header matching the configured token preserves existing behavior
   for representative administrative routers, including the
   ``incoming_messages`` pipeline entry point.
6. For ``admin_product_embeddings`` the local-admin flag is evaluated
   after authorization: an authorized request against a disabled
   flag still returns ``404`` without invoking the admin service.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.main as main_module
import backend.routers as routers_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import (
    ADMIN_TOKEN_HEADER,
    get_session,
    require_admin_token,
)

CONFIGURED_TOKEN = "test-admin-token-please-do-not-leak"

EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/webhooks/twilio/whatsapp/inbound",
        "/webhooks/twilio/whatsapp/status",
        "/admin/pilot/orders",
        "/admin/pilot/orders/{pedido_id}",
        "/admin/pilot/orders/{pedido_id}/local-test",
        "/admin/pilot/orders/commerce/{comercio_id}/catalog",
        "/admin/catalog/comercios",
        "/admin/catalog/comercios/{comercio_id}",
        "/admin/catalog/comercios/{comercio_id}/flavor",
        "/admin/catalog/comercios/{comercio_id}/categorias/nueva",
        "/admin/catalog/comercios/{comercio_id}/categorias/{categoria_id}/productos/nuevo",
        "/admin/catalog/comercios/{comercio_id}/presentaciones/nueva",
        "/admin/catalog/comercios/{comercio_id}/productos/{producto_id}/presentaciones/{presentacion_id}/precio/nuevo",
    }
)


def _settings(
    token: str | None = CONFIGURED_TOKEN,
    **overrides: object,
) -> Settings:
    base = settings_module.load_settings()
    payload = {**base.__dict__, "order_management_admin_token": token}
    payload.update(overrides)
    return Settings(**payload)


def _iter_api_routes():
    """Yield ``(path, dep_calls)`` for every APIRoute registered in
    ``backend.main.app`` at iteration time.

    FastAPI wraps each included router in an ``_IncludedRouter``
    object; this helper unwraps them so every APIRoute contributed by
    every included router is exposed. The yielded ``dep_calls`` list
    contains the callables recorded as router-level and route-level
    dependencies on the route's dependant tree.
    """
    # Imported lazily to avoid pinning the public FastAPI surface.
    from fastapi.routing import _IncludedRouter

    for route in main_module.app.routes:
        if isinstance(route, _IncludedRouter):
            for inner in route.original_router.routes:
                if not isinstance(inner, APIRoute):
                    continue
                yield inner.path, [dep.call for dep in inner.dependant.dependencies]
            continue
        if isinstance(route, APIRoute):
            yield route.path, [dep.call for dep in route.dependant.dependencies]


class _SessionOverride:
    """Explicit ``get_session`` override with a no-argument signature.

    Mirrors the helper used by the order-management security tests so
    FastAPI accepts it as a dependency with no required parameters
    while tests can still assert invocation counts.
    """

    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
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


class RemainingFastApiSurfaceInventoryTest(unittest.TestCase):
    """Route inventory derived from ``backend.main.app.routes``.

    The expected exempt surface is declared explicitly in
    ``EXEMPT_PATHS``; every other APIRoute registered by
    ``backend.main`` must carry ``require_admin_token``. Adding a
    new router without updating ``EXEMPT_PATHS`` (or without
    attaching the dependency) will fail this test with a message
    that names the unclassified path so the reviewer can either
    add the dependency or extend ``EXEMPT_PATHS`` through a
    reviewed change.
    """

    def test_inventory_lists_at_least_one_route(self) -> None:
        paths = [path for path, _ in _iter_api_routes()]
        self.assertGreater(
            len(paths),
            0,
            msg=(
                "no APIRoutes registered in backend.main; the inventory "
                "assertions below would silently pass on an empty surface"
            ),
        )

    def test_every_non_exempt_route_carries_require_admin_token(self) -> None:
        classified = 0
        for path, deps in _iter_api_routes():
            if path in EXEMPT_PATHS:
                continue
            classified += 1
            with self.subTest(path=path):
                self.assertIn(
                    require_admin_token,
                    deps,
                    msg=(
                        f"Route {path} must require the administrative "
                        "token; attach require_admin_token at router "
                        "scope or update EXEMPT_PATHS through a "
                        "reviewed change"
                    ),
                )
        self.assertGreater(
            classified,
            0,
            msg=(
                "no administrative routes were classified; the test "
                "would pass even if every router was removed from "
                "backend.main"
            ),
        )

    def test_every_exempt_route_does_not_carry_require_admin_token(self) -> None:
        seen: set[str] = set()
        for path, deps in _iter_api_routes():
            if path not in EXEMPT_PATHS:
                continue
            seen.add(path)
            with self.subTest(path=path):
                self.assertNotIn(
                    require_admin_token,
                    deps,
                    msg=(
                        f"Exempt route {path} must not depend on the "
                        "administrative-token dependency"
                    ),
                )
        self.assertEqual(
            seen,
            EXEMPT_PATHS,
            msg=(
                "expected exempt routes are not all registered in "
                f"backend.main; missing: {sorted(EXEMPT_PATHS - seen)}"
            ),
        )

    def test_health_endpoint_returns_200_without_admin_token(self) -> None:
        """``/health`` keeps its existing operational behavior with no
        administrative credential."""
        app = FastAPI()
        app.include_router(routers_module.health.router)
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class RemainingFastApiSurfaceConfigMissingTest(unittest.TestCase):
    """Server token absent or blank returns ``503`` and touches no
    database session or business service for representative
    administrative routers, including the incoming-message pipeline
    entry point and the embedding-admin routes."""

    REPRESENTATIVE_PATH_GET = "/comercios/1"
    REPRESENTATIVE_PATH_LIST = "/comercios"
    REPRESENTATIVE_PATH_INCOMING = (
        "/comercios/1/clientes/2/incoming-messages"
    )
    REPRESENTATIVE_PATH_EMBEDDINGS_REINDEX = (
        "/admin/comercios/1/product-embeddings/reindex"
    )
    REPRESENTATIVE_PATH_EMBEDDINGS_STATUS = (
        "/admin/comercios/1/product-embeddings/status"
    )

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = main_module.app
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings"
        )
        load_settings_mock = self._settings_patcher.start()
        load_settings_mock.return_value = _settings(token=None)

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _assert_no_business_work(self) -> None:
        self.session_override.assert_not_called()

    def test_comercios_get_returns_503_without_session_or_service(self) -> None:
        response = self.client.get(
            self.REPRESENTATIVE_PATH_GET,
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self._assert_no_business_work()

    def test_clientes_get_returns_503_without_session(self) -> None:
        response = self.client.get(
            "/clientes/9",
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()

    def test_sessions_get_returns_503_without_session(self) -> None:
        response = self.client.get(
            "/sessions/9",
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()

    def test_incoming_messages_post_returns_503_without_session(self) -> None:
        response = self.client.post(
            self.REPRESENTATIVE_PATH_INCOMING,
            json={"message": "hola"},
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()

    def test_embeddings_reindex_returns_503_without_session(self) -> None:
        response = self.client.post(
            self.REPRESENTATIVE_PATH_EMBEDDINGS_REINDEX,
            json={"dry_run": True},
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()

    def test_embeddings_status_returns_503_without_session(self) -> None:
        response = self.client.get(
            self.REPRESENTATIVE_PATH_EMBEDDINGS_STATUS,
            headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()

    def test_config_blank_returns_503_for_categorias(self) -> None:
        with patch.object(
            dependencies_module, "load_settings"
        ) as load_settings_mock:
            load_settings_mock.return_value = _settings(token="   ")
            response = self.client.get(
                "/comercios/1/categorias-productos",
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 503)
        self._assert_no_business_work()


class RemainingFastApiSurfaceUnauthorizedTest(unittest.TestCase):
    """Header absent, blank, or wrong returns ``401`` and touches no
    database session or business service for representative
    administrative routers, including ``incoming_messages`` and
    ``admin_product_embeddings``."""

    REPRESENTATIVE_PATHS_GET = (
        "/comercios/1",
        "/comercios/1/categorias-productos",
        "/comercios/1/presentaciones",
        "/comercios/1/productos",
        "/comercios/1/configuracion",
        "/productos/1/detalle",
        "/clientes/9",
        "/sessions/9",
    )
    REPRESENTATIVE_PATH_INCOMING = (
        "/comercios/1/clientes/2/incoming-messages"
    )
    REPRESENTATIVE_PATH_EMBEDDINGS_REINDEX = (
        "/admin/comercios/1/product-embeddings/reindex"
    )
    REPRESENTATIVE_PATH_EMBEDDINGS_STATUS = (
        "/admin/comercios/1/product-embeddings/status"
    )

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = main_module.app
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _assert_401(self, response) -> None:
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )
        self.session_override.assert_not_called()

    def test_header_absent_returns_401_for_each_router(self) -> None:
        for path in self.REPRESENTATIVE_PATHS_GET:
            with self.subTest(path=path):
                response = self.client.get(path)
                self._assert_401(response)

    def test_header_blank_returns_401(self) -> None:
        response = self.client.get(
            "/comercios/1",
            headers={ADMIN_TOKEN_HEADER: "   "},
        )
        self._assert_401(response)

    def test_header_empty_returns_401(self) -> None:
        response = self.client.get(
            "/comercios/1",
            headers={ADMIN_TOKEN_HEADER: ""},
        )
        self._assert_401(response)

    def test_header_wrong_returns_401(self) -> None:
        response = self.client.get(
            "/comercios/1",
            headers={ADMIN_TOKEN_HEADER: "definitely-not-the-token"},
        )
        self._assert_401(response)

    def test_header_wrong_returns_401_for_incoming_messages(self) -> None:
        response = self.client.post(
            self.REPRESENTATIVE_PATH_INCOMING,
            json={"message": "hola"},
            headers={ADMIN_TOKEN_HEADER: "also-wrong"},
        )
        self._assert_401(response)

    def test_header_absent_returns_401_for_incoming_messages(self) -> None:
        response = self.client.post(
            self.REPRESENTATIVE_PATH_INCOMING,
            json={"message": "hola"},
        )
        self._assert_401(response)

    def test_header_absent_returns_401_for_embeddings_reindex(self) -> None:
        response = self.client.post(
            self.REPRESENTATIVE_PATH_EMBEDDINGS_REINDEX,
            json={"dry_run": True},
        )
        self._assert_401(response)

    def test_header_absent_returns_401_for_embeddings_status(self) -> None:
        response = self.client.get(self.REPRESENTATIVE_PATH_EMBEDDINGS_STATUS)
        self._assert_401(response)


class RemainingFastApiSurfaceAuthorizedTest(unittest.TestCase):
    """Matching token preserves existing behavior for representative
    administrative routers, including the ``incoming_messages``
    pipeline entry point."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = main_module.app
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_comercios_get_with_matching_token_uses_session(self) -> None:
        with patch.object(
            routers_module.comercios, "ComercioService"
        ) as service_cls:
            service = MagicMock(name="ComercioService")
            service_cls.return_value = service
            service.get_by_id.return_value = MagicMock(
                id=1,
                nombre_fantasia="x",
                nombre_corto="x",
                razon_social="x",
                cuit="x",
                whatsapp="x",
                calle="x",
                numero="x",
                piso_departamento=None,
                localidad="x",
                provincia="x",
                codigo_postal="x",
                slug="x",
                estado_id=1,
                zona_horaria="x",
                moneda="x",
                idioma="x",
                fecha_alta="2026-08-11T12:00:00",
                fecha_ultima_modificacion="2026-08-11T12:00:00",
                fecha_baja=None,
            )
            response = self.client.get(
                "/comercios/1",
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        service.get_by_id.assert_called_once_with(1)

    def test_incoming_messages_post_with_matching_token_invokes_pipeline(
        self,
    ) -> None:
        with patch.object(
            routers_module.incoming_messages,
            "process_incoming_message_with_responses",
        ) as process_mock, patch.object(
            routers_module.incoming_messages.SessionService,
            "get_active",
        ) as get_active:
            from backend.intents.schemas.customer_response import CustomerResponse

            session = MagicMock(name="ConversationSession")
            get_active.return_value = session
            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="agregar_producto",
                    status="executed",
                )
            ]
            response = self.client.post(
                "/comercios/1/clientes/2/incoming-messages",
                json={"message": "hola"},
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        get_active.assert_called_once_with(1, 2)
        process_mock.assert_called_once()
        self.session_override.assert_called_once()


class RemainingFastApiSurfaceEmbeddingsFlagGateTest(unittest.TestCase):
    """For ``admin_product_embeddings`` the local-admin flag is
    evaluated after authorization: an authorized request against a
    disabled flag still returns ``404`` without invoking the admin
    service."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = main_module.app
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()
        self._admin_settings_patcher = patch.object(
            routers_module.admin_product_embeddings,
            "load_settings",
        )
        admin_settings_mock = self._admin_settings_patcher.start()
        admin_settings_mock.return_value = _settings(
            enable_local_admin_endpoints=False
        )

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._admin_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_authorized_request_with_disabled_flag_returns_404(
        self,
    ) -> None:
        with patch.object(
            routers_module.admin_product_embeddings,
            "ProductoPresentacionEmbeddingAdminService",
        ) as service_cls:
            response = self.client.post(
                "/admin/comercios/1/product-embeddings/reindex",
                json={"dry_run": True},
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
            response_get = self.client.get(
                "/admin/comercios/1/product-embeddings/status",
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response_get.status_code, 404)
        service_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)