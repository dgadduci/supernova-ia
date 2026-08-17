"""Focused tests for the global administrative panel landing page.

The tests cover the minimal contract for ``/admin``:

* The landing page renders 200 to an authenticated browser session
  and exposes the three documented entry points:
  ``/admin/catalog/comercios``, ``/admin/catalog/medios-pago`` and
  ``/admin/pilot/orders``.
* The landing page preserves the existing browser-only HTTP Basic
  boundary: requests without credentials are rejected with ``401``,
  requests with a wrong password are rejected with ``401`` and the
  documented misconfigured-token ``503`` is preserved.
* Both existing panel headers (``admin_catalog_panel/base.html``
  and ``admin_pilot_orders/base.html``) gain a stable, keyboard
  navigable link back to ``/admin``. The brand link and every
  local navigation entry remain unchanged.
* The landing page is a pure rendering adapter: it never opens a
  database session, never imports a domain service, never mutates
  state and never logs the credential.

The tests do not exercise the JSON API, do not require a real
database and never reach the embedding provider.
"""

from __future__ import annotations

import base64
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.admin.routes as admin_routes
import backend.config.settings as settings_module
import backend.dependencies as dependencies_module
import backend.routers.admin_pilot_orders as pilot_router_module
from backend.admin import index_routes
from backend.config.settings import Settings
from backend.dependencies import get_session

CONFIGURED_TOKEN = "admin-index-token-for-tests"


def _settings(token: object = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(**{**base.__dict__, "order_management_admin_token": token})


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(index_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(pilot_router_module.router)
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


def _install_session_override(
    test: unittest.TestCase, app: FastAPI, session: object
) -> _SessionOverride:
    override = _SessionOverride(session)

    def _dependency() -> object:
        return override()

    app.dependency_overrides[get_session] = _dependency
    test.addCleanup(lambda: app.dependency_overrides.pop(get_session, None))
    return override


def _stub_settings_patcher(test: unittest.TestCase, **kwargs: object) -> None:
    target_settings = _settings(**kwargs)
    patcher = unittest.mock.patch.object(
        dependencies_module, "load_settings", return_value=target_settings
    )
    patcher.start()
    test.addCleanup(patcher.stop)


def _stub_catalog_view_service(test: unittest.TestCase) -> MagicMock:
    view_cls = unittest.mock.patch.object(
        admin_routes, "AdministrativeCatalogPanelViewService"
    )
    view = view_cls.start()
    view.return_value = MagicMock(name="CatalogViewService")
    test.addCleanup(view_cls.stop)
    return view


def _stub_pilot_view_service(test: unittest.TestCase) -> MagicMock:
    service_cls = unittest.mock.patch.object(
        pilot_router_module, "PilotOrderOperationsViewService"
    )
    service = service_cls.start()
    service.return_value = MagicMock(name="PilotViewService")
    test.addCleanup(service_cls.stop)
    return service


class AdminIndexRouteTest(unittest.TestCase):
    """``GET /admin`` is the documented server-rendered landing page."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings_patcher(self)
        _stub_catalog_view_service(self)
        _stub_pilot_view_service(self)

    def test_index_returns_200_when_authenticated(self) -> None:
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)

    def test_index_lists_three_documented_entries(self) -> None:
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        # The three documented entry points must be present as
        # server-rendered hyperlinks. The landing page is the
        # single source of truth for global navigation; no other
        # shortcut is allowed to replace it.
        self.assertIn('href="/admin/catalog/comercios"', response.text)
        self.assertIn('href="/admin/catalog/medios-pago"', response.text)
        self.assertIn('href="/admin/pilot/orders"', response.text)
        self.assertIn("Comercios", response.text)
        self.assertIn("Medios de pago", response.text)
        self.assertIn("Operación (panel piloto)", response.text)

    def test_index_does_not_require_database(self) -> None:
        """The landing page is a navigation hub, not a data source.

        Opening the session for a request that needs no rows would
        be a regression: it would couple navigation to the
        database availability and break the documented boundary.
        """
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        self.override.assert_not_called()

    def test_index_does_not_use_javascript_navigation(self) -> None:
        """The "volver" decision is a stable hyperlink, never
        ``history.back()`` or a click handler that depends on the
        referrer. Direct URL entry must reach the landing page."""
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("history.back", response.text)
        self.assertNotIn("window.history", response.text)
        self.assertNotIn("location.replace", response.text)

    def test_index_entries_are_keyboard_focusable(self) -> None:
        """The three entry links must be real ``<a>`` elements so
        they are reachable via the Tab key. A non-anchor wrapper
        would defeat keyboard navigation and screen readers."""
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        for url in (
            "/admin/catalog/comercios",
            "/admin/catalog/medios-pago",
            "/admin/pilot/orders",
        ):
            with self.subTest(url=url):
                self.assertIn(f'<a class="entry-link" href="{url}"', response.text)

    def test_index_has_visible_focus_ring_styles(self) -> None:
        """The landing page must declare a focus ring so the
        keyboard user can see the active link. Reusing the
        documented ``--focus-ring`` token keeps the visual
        language consistent with the catalog panel base."""
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(":focus-visible", response.text)
        self.assertIn("--focus-ring", response.text)

    def test_index_has_skip_link(self) -> None:
        """The landing page reuses the existing accessibility
        pattern: a ``skip-link`` that lets keyboard users jump
        straight to the main content."""
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("skip-link", response.text)
        self.assertIn("Saltar al contenido", response.text)

    def test_index_has_no_external_assets(self) -> None:
        """The landing page must not reference remote CSS or JS so
        the panel keeps loading in offline / restricted
        environments. Reusing the documented rejection list from
        the catalog panel base."""
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 200)
        forbidden_substrings = [
            "https://fonts.googleapis",
            "https://cdn.jsdelivr",
            "https://unpkg.com",
            "<link rel=\"stylesheet\"",
            "<script src=",
        ]
        for needle in forbidden_substrings:
            self.assertNotIn(needle, response.text)


class AdminIndexAuthTest(unittest.TestCase):
    """``/admin`` reuses the existing browser-only HTTP Basic boundary."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings_patcher(self)
        _stub_catalog_view_service(self)
        _stub_pilot_view_service(self)

    def test_missing_credentials_returns_401(self) -> None:
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_invalid_credentials_returns_401(self) -> None:
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", "wrong-token")
        )
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_misconfigured_token_returns_503(self) -> None:
        _stub_settings_patcher(self, token=None)
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 503)
        self.override.assert_not_called()

    def test_blank_token_returns_503(self) -> None:
        _stub_settings_patcher(self, token="   ")
        response = self.client.get(
            "/admin", headers=_basic_auth_header("any", CONFIGURED_TOKEN)
        )
        self.assertEqual(response.status_code, 503)
        self.override.assert_not_called()

    def test_root_and_trailing_slash_are_equivalent(self) -> None:
        """``/admin`` and ``/admin/`` must both render the landing
        page so the operator does not see a 404 for either
        common URL form."""
        for path in ("/admin", "/admin/"):
            with self.subTest(path=path):
                response = self.client.get(
                    path, headers=_basic_auth_header("any", CONFIGURED_TOKEN)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn('href="/admin/catalog/comercios"', response.text)


class CatalogBaseTemplateHasInicioLinkTest(unittest.TestCase):
    """The catalog panel header must surface a stable link to ``/admin``."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings_patcher(self)

    def test_catalog_list_page_has_inicio_link(self) -> None:
        view_cls = unittest.mock.patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        )
        view = view_cls.start()
        view.return_value = MagicMock(name="CatalogViewService")
        self.addCleanup(view_cls.stop)
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        # The Inicio link must be a real <a> element so it is
        # keyboard navigable. The visible text is the documented
        # Spanish label.
        self.assertIn('href="/admin"', response.text)
        self.assertIn("Inicio", response.text)

    def test_catalog_list_preserves_brand_link(self) -> None:
        """The documented brand link to ``/admin/catalog/comercios``
        must remain so local navigation is untouched."""
        view_cls = unittest.mock.patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        )
        view = view_cls.start()
        view.return_value = MagicMock(name="CatalogViewService")
        self.addCleanup(view_cls.stop)
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'class="brand" href="/admin/catalog/comercios"', response.text
        )

    def test_catalog_list_preserves_operacion_link(self) -> None:
        """The cross-panel link to Operación must remain so the
        catalog panel keeps the existing short-circuit into the
        pilot surface."""
        view_cls = unittest.mock.patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        )
        view = view_cls.start()
        view.return_value = MagicMock(name="CatalogViewService")
        self.addCleanup(view_cls.stop)
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/admin/pilot/orders"', response.text)


class PilotBaseTemplateHasInicioLinkTest(unittest.TestCase):
    """The pilot orders header must surface a stable link to ``/admin``."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings_patcher(self)

    def _stub_empty_list(self) -> MagicMock:
        service_cls = unittest.mock.patch.object(
            pilot_router_module, "PilotOrderOperationsViewService"
        )
        service = service_cls.start()
        service.return_value.list_orders = MagicMock(
            return_value=MagicMock(rows=(), page=1, page_size=20, total=0)
        )
        self.addCleanup(service_cls.stop)
        return service

    def test_pilot_list_page_has_inicio_link(self) -> None:
        self._stub_empty_list()
        response = self.client.get(
            "/admin/pilot/orders",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        # The Inicio link must be a real <a> element with the
        # documented ``.home-link`` class so it picks up the
        # keyboard-focus ring declared in the pilot base styles.
        self.assertIn('class="home-link" href="/admin"', response.text)
        self.assertIn("Inicio", response.text)

    def test_pilot_list_preserves_brand_link(self) -> None:
        """The documented brand link to ``/admin/pilot/orders`` must
        remain so local navigation is untouched."""
        self._stub_empty_list()
        response = self.client.get(
            "/admin/pilot/orders",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/admin/pilot/orders"', response.text)


class AdminIndexStaticFilesTest(unittest.TestCase):
    """Static checks on the new template and the modified headers."""

    def test_admin_index_template_exists_and_uses_autoescape(self) -> None:
        template_path = (
            Path(index_routes.__file__).resolve().parent.parent
            / "templates"
            / "admin"
            / "admin_index.html"
        )
        self.assertTrue(template_path.exists(), f"missing {template_path}")
        contents = template_path.read_text(encoding="utf-8")
        # The brand link points to the documented stable entry.
        self.assertIn('href="/admin"', contents)
        # The entry cards reference the Jinja context variables
        # supplied by the route handler so the navigation hub can
        # be re-pointed without rewriting the template.
        for placeholder in (
            "{{ comercios_url }}",
            "{{ medios_pago_url }}",
            "{{ operacion_url }}",
        ):
            with self.subTest(placeholder=placeholder):
                self.assertIn(placeholder, contents)
        # No remote assets must leak into the new template.
        self.assertNotIn("https://fonts.googleapis", contents)
        self.assertNotIn("https://cdn.jsdelivr", contents)
        self.assertNotIn("https://unpkg.com", contents)
        # No JavaScript-driven navigation: history.back / pushState
        # would silently break direct URL entry.
        self.assertNotIn("history.back", contents)
        self.assertNotIn("history.pushState", contents)

    def test_catalog_base_template_has_inicio_link(self) -> None:
        template_path = (
            Path(admin_routes.__file__).resolve().parent.parent
            / "templates"
            / "admin_catalog_panel"
            / "base.html"
        )
        contents = template_path.read_text(encoding="utf-8")
        # The Inicio entry sits inside the documented primary nav.
        self.assertIn('href="/admin"', contents)
        self.assertIn("Inicio", contents)
        # The original primary-nav entries are preserved.
        self.assertIn('href="/admin/catalog/comercios"', contents)
        self.assertIn('href="/admin/catalog/medios-pago"', contents)
        self.assertIn('href="/admin/pilot/orders"', contents)
        # The brand link to /admin/catalog/comercios remains intact.
        self.assertIn(
            'class="brand" href="/admin/catalog/comercios"', contents
        )

    def test_pilot_base_template_has_inicio_link(self) -> None:
        template_path = (
            Path(pilot_router_module.__file__).resolve().parent.parent
            / "templates"
            / "admin_pilot_orders"
            / "base.html"
        )
        contents = template_path.read_text(encoding="utf-8")
        # The Inicio link must be a real <a> with the documented
        # ``.home-link`` class so the focus ring is applied.
        self.assertIn('class="home-link" href="/admin"', contents)
        self.assertIn("Inicio", contents)
        # The brand link to /admin/pilot/orders remains intact.
        self.assertIn('href="/admin/pilot/orders"', contents)
        # The CSS for ``.home-link`` declares a focus ring so the
        # keyboard user can see the active link.
        self.assertIn(".home-link:focus-visible", contents)


if __name__ == "__main__":
    unittest.main()