"""Focused tests for the administrative catalog panel.

The tests cover the bounded browser surface the OpenSpec change
authorises:

* HTTP Basic authentication: missing, invalid, misconfigured, and
  consistent JSON-API (``X-Admin-Token``) contracts.
* Stateless anti-CSRF: every state-changing form must carry a
  path-bound nonce field (``_csrf_nonce``) and a same-origin
  ``Origin`` (or ``Referer``) header. Missing nonce, wrong nonce,
  nonce from a foreign route, missing origin header, and
  cross-origin ``Origin`` are all rejected with a bounded ``400``
  and perform no mutation. The check stays active by default and
  never weakens the existing JSON ``X-Admin-Token`` boundary.
* Commerce list and exact commerce detail configuration read.
* Flavor assignment / clear through the existing authoritative
  boundary and absence of ``instruccion_llm`` leakage.
* The four panel-creation flows (category, product, presentation,
  price) preserve the existing validation, transaction and
  post-create embedding synchronization contract through the shared
  :class:`CatalogCreateService`.
* Commerce isolation: nested ids from a foreign commerce are
  rejected without mutating state.
* Visual / accessibility hooks: keyboard focus, non-colour status
  text, responsive layout markers, no external assets.

The tests stub :class:`CatalogCreateService` for the create paths
so no real database or embedding provider is touched.
"""
from __future__ import annotations

import base64
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.admin.routes as admin_routes
import backend.dependencies as dependencies_module
import backend.main as main_module
import backend.routers.admin_pilot_orders as pilot_router_module
from backend.admin.views import (
    CatalogCategoriaDetailView,
    CatalogCategoriaRow,
    CatalogPresentacionRow,
    CatalogProductoDetailView,
    CatalogProductoPresentacionRow,
    CatalogProductoRow,
    CommerceCatalogNavigationView,
    CommerceDeliveryActiveCandidate,
    CommerceDetailView,
    CommercePaymentActiveCandidate,
    CommerceSummary,
    DeliveryMethodDetailView,
    FlavorOption,
    FlavorSummaryView,
    GlobalMedioPagoRow,
    InactiveDeliveryMethodDetailView,
    InactivePaymentMethodDetailView,
    PaymentMethodDetailView,
)
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import (
    ADMIN_TOKEN_HEADER,
    PANEL_FORM_NONCE_FIELD,
    compute_panel_form_nonce,
    get_session,
    resolve_panel_csrf_secret,
)

CONFIGURED_TOKEN = "admin-panel-token-for-tests"
NONCE_FIELD = PANEL_FORM_NONCE_FIELD
TESTCLIENT_ORIGIN = "http://testserver"


def _settings(
    token: object = CONFIGURED_TOKEN,
    *,
    csrf_secret: object = None,
    allowed_origin: object = None,
    **overrides: object,
) -> Settings:
    base = settings_module.load_settings()
    payload = {**base.__dict__, "order_management_admin_token": token}
    payload["admin_panel_csrf_secret"] = csrf_secret
    payload["admin_panel_allowed_origin"] = allowed_origin
    payload.update(overrides)
    return Settings(**payload)


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _csrf_form_data(path: str, extra: dict[str, str]) -> dict[str, str]:
    """Return form data containing the path-bound CSRF nonce.

    The nonce is recomputed for ``path`` from the resolved secret so
    a regular HTML form post (no JavaScript, no custom headers) is
    accepted. The extra form fields are merged verbatim so the
    caller can keep using ``_csrf_form_data(path, {"field": "v"})``
    in every test.
    """
    nonce = compute_panel_form_nonce(
        path=path,
        secret=resolve_panel_csrf_secret(),
    )
    return {NONCE_FIELD: nonce, **extra}


def _same_origin_headers() -> dict[str, str]:
    """Return the same-origin ``Origin`` header TestClient uses."""
    return {"Origin": TESTCLIENT_ORIGIN}


def _same_origin_referer_headers(path: str) -> dict[str, str]:
    """Return the same-origin ``Referer`` header for ``path``."""
    return {"Referer": f"{TESTCLIENT_ORIGIN}{path}"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
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


@dataclass(frozen=True)
class _FlavorStub:
    id: int
    codigo: str
    nombre: str
    descripcion: str
    version: int


def _stub_view_service(
    *,
    comercios: list[CommerceSummary] | None = None,
    detail: CommerceDetailView | None = None,
    catalog: CommerceCatalogNavigationView | None = None,
    flavor_options: list[FlavorOption] | None = None,
    categoria: CatalogCategoriaDetailView | None = None,
    producto: CatalogProductoDetailView | None = None,
    pp: CatalogProductoPresentacionRow | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        list_comercios=MagicMock(return_value=comercios or []),
        get_commerce_detail=MagicMock(return_value=detail),
        get_commerce_catalog_navigation=MagicMock(return_value=catalog),
        list_active_flavors=MagicMock(return_value=flavor_options or []),
        get_categoria_detail=MagicMock(return_value=categoria),
        get_producto_detail=MagicMock(return_value=producto),
        find_producto_presentacion=MagicMock(return_value=pp),
        find_producto_presentacion_for_pp=MagicMock(return_value=pp),
    )


def _stub_create_service(
    *,
    create_categoria=MagicMock(),
    create_producto=MagicMock(),
    create_presentacion=MagicMock(),
    create_precio=MagicMock(),
    assign_flavor=MagicMock(),
) -> SimpleNamespace:
    return SimpleNamespace(
        create_categoria_producto=create_categoria,
        create_producto=create_producto,
        create_presentacion=create_presentacion,
        create_precio=create_precio,
        assign_flavor=assign_flavor,
    )


def _stub_settings_patcher(test: unittest.TestCase, **kwargs: object) -> None:
    settings = _settings(**kwargs)
    patcher = patch.object(
        dependencies_module, "load_settings", return_value=settings
    )
    patcher.start()
    test.addCleanup(patcher.stop)


def _install_session_override(
    test: unittest.TestCase, app: FastAPI, session: object
) -> _SessionOverride:
    override = _SessionOverride(session)
    app.dependency_overrides[get_session] = override
    test.addCleanup(app.dependency_overrides.clear)
    return override


def _build_detail() -> CommerceDetailView:
    return CommerceDetailView(
        id=1,
        nombre_fantasia="Comercio <b>",
        nombre_corto="X",
        razon_social="X SRL",
        cuit="30-12345678-9",
        whatsapp="+5491100000001",
        calle="Calle 1",
        numero="100",
        piso_departamento=None,
        localidad="CABA",
        provincia="CABA",
        codigo_postal="1000",
        slug="comercio-x",
        estado="ACTIVO",
        zona_horaria="America/Argentina/Buenos_Aires",
        moneda="ARS",
        idioma="es-AR",
        medios_pago=[
            PaymentMethodDetailView(
                id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                titular=None,
                alias=None,
            ),
            PaymentMethodDetailView(
                id=11,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                activo=False,
                titular="Comercio X",
                alias="alias.test",
            ),
        ],
        metodos_entrega=[
            DeliveryMethodDetailView(
                id=20,
                codigo="RETIRO",
                descripcion="Retiro en local",
                activo=True,
                orden=1,
            ),
            DeliveryMethodDetailView(
                id=21,
                codigo="DELIVERY",
                descripcion="Envío a domicilio",
                activo=False,
                orden=2,
            ),
        ],
        flavor=FlavorSummaryView(
            id=2,
            codigo="neutro",
            nombre="Neutro",
            descripcion="Mensaje neutral",
            version=1,
            activo=True,
        ),
    )


def _build_catalog() -> CommerceCatalogNavigationView:
    return CommerceCatalogNavigationView(
        comercio_id=1,
        categorias=[
            CatalogCategoriaRow(id=100, descripcion="Panificados", activo=True, orden=1),
        ],
        presentaciones=[
            CatalogPresentacionRow(
                id=200,
                codigo="KG",
                descripcion="Bolsa x 1 kg",
                activo=True,
                orden=1,
            ),
        ],
    )


def _build_flavor_options() -> list[FlavorOption]:
    return [
        FlavorOption(id=2, codigo="neutro", nombre="Neutro", descripcion="Mensaje neutral", version=1),
        FlavorOption(id=3, codigo="amigable", nombre="Amigable", descripcion="Mensaje cálido", version=1),
    ]


class PanelAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_missing_credential_returns_401(self) -> None:
        response = self.client.get("/admin/catalog/comercios")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )
        self.assertEqual(response.headers.get("www-authenticate"), "Basic")
        self.override.assert_not_called()

    def test_wrong_password_returns_401(self) -> None:
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", "definitely-wrong"),
        )
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_correct_password_with_ignored_username_succeeds(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service(
                comercios=[
                    CommerceSummary(
                        id=1,
                        nombre_fantasia="X",
                        nombre_corto="X",
                        estado="ACTIVO",
                        flavor_codigo="neutro",
                        flavor_nombre="Neutro",
                        tiene_flavor=True,
                    )
                ]
            )
            response = self.client.get(
                "/admin/catalog/comercios",
                headers=_basic_auth_header("ignored-user", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_no_cookie_or_token_persisted(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service(comercios=[])
            response = self.client.get(
                "/admin/catalog/comercios",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("set-cookie", {k.lower() for k in response.headers})


class PanelAuthMisconfiguredTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)

    def test_token_none_returns_503(self) -> None:
        _stub_settings_patcher(self, token=None)
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self.override.assert_not_called()

    def test_blank_token_returns_503(self) -> None:
        _stub_settings_patcher(self, token="   ")
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 503)
        self.override.assert_not_called()


class PanelPreservesJsonApiTest(unittest.TestCase):
    """The new panel does not weaken the existing JSON API
    authentication contract: every JSON endpoint still requires
    ``X-Admin-Token`` and rejects Basic auth."""

    def setUp(self) -> None:
        self.app = main_module.app
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        self.session = MagicMock(name="DatabaseSession")
        self.override = _install_session_override(self, self.app, self.session)
        _stub_settings_patcher(self)

    def test_comercios_get_rejects_basic_auth(self) -> None:
        response = self.client.get(
            "/comercios/1",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_comercios_get_accepts_token_header(self) -> None:
        import backend.routers.comercios as comercios_router_module

        with patch.object(
            comercios_router_module,
            "ComercioService",
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
                flavor_comunicacion=None,
            )
            response = self.client.get(
                "/comercios/1",
                headers={ADMIN_TOKEN_HEADER: CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        service.get_by_id.assert_called_once_with(1)

    def test_pilot_panel_regression_keeps_working(self) -> None:
        with patch.object(
            pilot_router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = MagicMock(
                list_orders=MagicMock(),
                get_detail=MagicMock(),
                get_provider_history=MagicMock(),
                get_order_lines_snapshot=MagicMock(),
            )
            service_cls.return_value.list_orders.return_value = SimpleNamespace(
                rows=[],
                total=0,
                page=1,
                page_size=25,
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)


class PanelCsrfGuardTest(unittest.TestCase):
    """State-changing panel submissions must carry the documented
    path-bound nonce ``_csrf_nonce`` form field and a same-origin
    ``Origin`` (or ``Referer``) header. Missing nonce, wrong nonce,
    nonce from a foreign route, missing origin header and
    cross-origin ``Origin`` all yield a bounded ``400`` and perform
    no mutation. GET requests bypass the dependency."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_flavor_mutation_without_nonce_is_rejected(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                "/admin/catalog/comercios/1/flavor",
                headers=self._auth_headers(),
                data={"flavor_comunicacion_id": "2"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("csrf", response.text.lower())
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_flavor_mutation_without_origin_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("origen", response.text.lower())
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_categoria_create_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={"descripcion": "Panificados", "activo": "true", "orden": "1"},
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_categoria_producto.assert_not_called()

    def test_producto_create_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/categorias/100/productos/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={"nombre": "Pan", "activo": "true", "disponible": "true", "orden": "1"},
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_producto.assert_not_called()

    def test_presentacion_create_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/presentaciones/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={"codigo": "KG", "descripcion": "Bolsa", "activo": "true", "orden": "1"},
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_presentacion.assert_not_called()

    def test_precio_create_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/productos/1000/presentaciones/200/precio/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={"precio": "150.00"},
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_precio.assert_not_called()

    def test_native_html_post_without_javascript_or_header_works(self) -> None:
        """A regular HTML POST with the nonce field and a same-origin
        ``Origin`` header — no JavaScript, no custom headers — must
        succeed end-to-end and call the shared service exactly once.
        """
        path = "/admin/catalog/comercios/1/categorias/nueva"
        new_row = MagicMock(name="CategoriaRow")
        new_row.id = 555
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_categoria=MagicMock(return_value=new_row)
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {"descripcion": "Panificados", "activo": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 303)
        create_cls.return_value.create_categoria_producto.assert_called_once()

    def test_missing_token_is_rejected_without_mutation(self) -> None:
        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={
                    "descripcion": "Panificados",
                    "activo": "true",
                    "orden": "1",
                },
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_categoria_producto.assert_not_called()

    def test_invalid_token_is_rejected_without_mutation(self) -> None:
        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={
                    NONCE_FIELD: "0" * 64,
                    "descripcion": "Panificados",
                    "activo": "true",
                    "orden": "1",
                },
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_categoria_producto.assert_not_called()

    def test_token_from_another_route_is_rejected(self) -> None:
        """The nonce is path-bound; a nonce minted for a different
        route must never unlock a state-changing submission."""
        target = "/admin/catalog/comercios/1/categorias/nueva"
        other = "/admin/catalog/comercios/1/presentaciones/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                target,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    other,
                    {"descripcion": "Panificados", "activo": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.create_categoria_producto.assert_not_called()

    def test_cross_origin_origin_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Origin": "https://attacker.example.test",
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_missing_origin_with_valid_referer_is_accepted(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=MagicMock(
                    return_value=(
                        MagicMock(name="Comercio"),
                        _FlavorStub(2, "neutro", "Neutro", "Mensaje neutral", 1),
                    )
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_referer_headers(path),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 200)
        create_cls.return_value.assign_flavor.assert_called_once_with(1, 2)

    def test_missing_origin_and_referer_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_get_routes_are_not_csrf_checked(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls:
            view_cls.return_value = _stub_view_service(comercios=[])
            response = self.client.get(
                "/admin/catalog/comercios",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)


class PanelCsrfOriginAllowlistTest(unittest.TestCase):
    """When the operator pins a panel origin via configuration,
    submissions are accepted only when the ``Origin`` (or parsed
    ``Referer``) origin matches the configured value."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(
            self,
            allowed_origin="https://panel.example.test",
        )

    def test_origin_mismatch_rejects_flavor_submission(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Origin": "https://attacker.example.test",
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_origin_match_accepts_flavor_submission(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=MagicMock(
                    return_value=(
                        MagicMock(name="Comercio"),
                        _FlavorStub(2, "neutro", "Neutro", "Mensaje neutral", 1),
                    )
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Origin": "https://panel.example.test",
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 200)

    def test_origin_match_via_referer_accepts_flavor_submission(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=MagicMock(
                    return_value=(
                        MagicMock(name="Comercio"),
                        _FlavorStub(2, "neutro", "Neutro", "Mensaje neutral", 1),
                    )
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Referer": "https://panel.example.test/admin/catalog/comercios/1",
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 200)

    def test_referer_origin_mismatch_rejects_flavor_submission(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Referer": "https://attacker.example.test/admin/catalog/comercios/1",
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.assign_flavor.assert_not_called()


class PanelListViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_list_renders_bounded_summary(self) -> None:
        rows = [
            CommerceSummary(
                id=1,
                nombre_fantasia="<b>Comercio X</b>",
                nombre_corto="X",
                estado="ACTIVO",
                flavor_codigo="neutro",
                flavor_nombre="Neutro",
                tiene_flavor=True,
            ),
            CommerceSummary(
                id=2,
                nombre_fantasia="Comercio Y",
                nombre_corto="Y",
                estado="INACTIVO",
                flavor_codigo=None,
                flavor_nombre=None,
                tiene_flavor=False,
            ),
        ]
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service = _stub_view_service(comercios=rows)
            service_cls.return_value = service
            response = self.client.get(
                "/admin/catalog/comercios",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Comercio X", response.text)
        self.assertNotIn("<b>Comercio X</b>", response.text)
        self.assertIn("Sin flavor", response.text)

    def test_detail_renders_exact_configuration(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            service_cls.return_value = service
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Comercio &lt;b&gt;", response.text)
        self.assertIn("Efectivo", response.text)
        self.assertIn("Retiro en local", response.text)
        self.assertIn("neutro", response.text)

    def test_detail_with_missing_comercio_returns_404(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service = _stub_view_service(detail=None, catalog=None)
            service_cls.return_value = service
            response = self.client.get(
                "/admin/catalog/comercios/9999",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("No encontrado", response.text)

    def test_detail_with_invalid_id_returns_400(self) -> None:
        response = self.client.get(
            "/admin/catalog/comercios/abc",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Solicitud inválida", response.text)


class PanelFlavorPrivacyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_detail_never_renders_instruccion_llm(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            service_cls.return_value = service
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("instruccion_llm", response.text)
        self.assertNotIn("INSTRUCCION_LLM", response.text)

    def test_detail_flavor_form_nonce_is_bound_to_flavor_post_target(self) -> None:
        """The detail GET and flavor POST have different paths.

        The rendered nonce must be generated for the POST destination, not
        the detail page itself, otherwise a native browser submission is
        rejected before the flavor service is reached.
        """
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        expected_nonce = compute_panel_form_nonce(
            path="/admin/catalog/comercios/1/flavor",
            secret=resolve_panel_csrf_secret(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'name="{NONCE_FIELD}" value="{expected_nonce}"',
            response.text,
        )

    def test_assign_flavor_passes_value_to_shared_service(self) -> None:
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            assign_mock = MagicMock(
                return_value=(
                    MagicMock(name="Comercio"),
                    _FlavorStub(2, "neutro", "Neutro", "Mensaje neutral", 1),
                )
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 200)
        assign_mock.assert_called_once_with(1, 2)

    def test_clear_flavor_uses_none(self) -> None:
        """The real HTML payload ``flavor_comunicacion_id=`` (the
        ``— Sin flavor —`` option) must reach the shared service as
        ``None``; Pydantic must never reject the empty string before
        the field is normalised.
        """
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            assign_mock = MagicMock(
                return_value=(
                    MagicMock(name="Comercio"),
                    None,
                )
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": ""}),
            )
        self.assertEqual(response.status_code, 200)
        assign_mock.assert_called_once_with(1, None)
        self.assertIn("Flavor limpiado", response.text)

    def test_clear_flavor_with_whitespace_only_value_uses_none(self) -> None:
        """Whitespace-only values must normalise to ``None`` too so the
        operator cannot bypass the clear semantics with stray spaces.
        """
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            assign_mock = MagicMock(
                return_value=(
                    MagicMock(name="Comercio"),
                    None,
                )
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "   "}),
            )
        self.assertEqual(response.status_code, 200)
        assign_mock.assert_called_once_with(1, None)

    def test_assign_flavor_zero_value_does_not_invoke_service(self) -> None:
        """``0`` is not a valid flavor id and must be rejected at the
        form adapter so the shared service is never called."""
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "0"}),
            )
        self.assertEqual(response.status_code, 422)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_assign_flavor_negative_value_does_not_invoke_service(self) -> None:
        """Negative ids must be rejected at the form adapter."""
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "-1"}),
            )
        self.assertEqual(response.status_code, 422)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_assign_flavor_non_numeric_value_does_not_invoke_service(self) -> None:
        """Magic codes / sentinels like ``"neutro"`` must be rejected at
        the form adapter so the shared service never sees them."""
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "neutro"}),
            )
        self.assertEqual(response.status_code, 422)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_clear_flavor_still_requires_nonce_and_origin(self) -> None:
        """The clear payload must continue to carry a valid path-bound
        nonce and a same-origin header; the normalisation helper must
        not weaken the CSRF boundary."""
        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            create_cls.return_value = _stub_create_service()
            response = self.client.post(
                path,
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
                data={NONCE_FIELD: "0" * 64, "flavor_comunicacion_id": ""},
            )
        self.assertEqual(response.status_code, 400)
        create_cls.return_value.assign_flavor.assert_not_called()

    def test_assign_unknown_flavor_renders_bounded_error(self) -> None:
        from backend.services.exceptions import FlavorComunicacionNotFound

        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            assign_mock = MagicMock(
                side_effect=FlavorComunicacionNotFound(999)
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "999"}),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("El flavor seleccionado no existe", response.text)

    def test_assign_inactive_flavor_renders_bounded_error(self) -> None:
        from backend.services.exceptions import FlavorComunicacionInactivo

        path = "/admin/catalog/comercios/1/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            assign_mock = MagicMock(
                side_effect=FlavorComunicacionInactivo(99)
            )
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "99"}),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("inactivo", response.text.lower())

    def test_assign_missing_comercio_renders_not_found(self) -> None:
        from backend.services.exceptions import ComercioNotFound

        path = "/admin/catalog/comercios/999/flavor"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service()
            assign_mock = MagicMock(side_effect=ComercioNotFound(999))
            create_cls.return_value = _stub_create_service(
                assign_flavor=assign_mock
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"flavor_comunicacion_id": "2"}),
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("No encontrado", response.text)


class PanelCreateCategoriaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_create_categoria_success_redirects(self) -> None:
        new_row = MagicMock(name="CategoriaRow")
        new_row.id = 500
        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_categoria=MagicMock(return_value=new_row)
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"descripcion": "Panificados", "activo": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/admin/catalog/comercios/1", response.headers["location"])
        create_cls.return_value.create_categoria_producto.assert_called_once()

    def test_create_categoria_invalid_descripcion_renders_error(self) -> None:
        from backend.services.exceptions import InvalidCategoriaProducto

        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_categoria=MagicMock(
                    side_effect=InvalidCategoriaProducto("descripcion must not be empty")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"descripcion": "   ", "activo": "true", "orden": "0"},
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("categoría enviada no es válida", response.text)

    def test_create_categoria_duplicate_render_error(self) -> None:
        from backend.services.exceptions import InvalidCategoriaProducto

        path = "/admin/catalog/comercios/1/categorias/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_categoria=MagicMock(
                    side_effect=InvalidCategoriaProducto("descripcion must not be empty")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"descripcion": "Panificados", "activo": "true", "orden": "0"},
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("categoría enviada no es válida", response.text)


class PanelCreateProductoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_create_producto_success_redirects(self) -> None:
        new_row = MagicMock(name="ProductoRow")
        new_row.id = 700
        categoria = CatalogCategoriaDetailView(
            id=100,
            id_comercio=1,
            descripcion="Panificados",
            activo=True,
            orden=1,
            productos=[],
        )
        path = "/admin/catalog/comercios/1/categorias/100/productos/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), categoria=categoria
            )
            create_cls.return_value = _stub_create_service(
                create_producto=MagicMock(return_value=new_row)
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {
                        "nombre": "Pan",
                        "descripcion": "Pan fresco",
                        "activo": "true",
                        "disponible": "true",
                        "orden": "1",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)

    def test_create_producto_duplicate_in_categoria_renders_bounded_error(self) -> None:
        from backend.services.exceptions import DuplicateProductoNombre

        categoria = CatalogCategoriaDetailView(
            id=100,
            id_comercio=1,
            descripcion="Panificados",
            activo=True,
            orden=1,
            productos=[
                CatalogProductoRow(
                    id=1,
                    nombre="Pan",
                    descripcion=None,
                    activo=True,
                    disponible=True,
                    orden=1,
                )
            ],
        )
        path = "/admin/catalog/comercios/1/categorias/100/productos/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), categoria=categoria
            )
            create_cls.return_value = _stub_create_service(
                create_producto=MagicMock(
                    side_effect=DuplicateProductoNombre("Pan")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"nombre": "Pan", "activo": "true", "disponible": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ya existe un producto con ese nombre", response.text)

    def test_create_producto_invalid_nombre_renders_bounded_error(self) -> None:
        from backend.services.exceptions import InvalidProducto

        categoria = CatalogCategoriaDetailView(
            id=100,
            id_comercio=1,
            descripcion="Panificados",
            activo=True,
            orden=1,
            productos=[],
        )
        path = "/admin/catalog/comercios/1/categorias/100/productos/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), categoria=categoria
            )
            create_cls.return_value = _stub_create_service(
                create_producto=MagicMock(
                    side_effect=InvalidProducto("nombre must not be empty")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"nombre": "   ", "activo": "true", "disponible": "true", "orden": "0"},
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("El producto enviado no es válido", response.text)

    def test_create_producto_foreign_categoria_returns_404(self) -> None:
        path = "/admin/catalog/comercios/1/categorias/999/productos/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), categoria=None
            )
            create_cls.return_value = _stub_create_service(
                create_producto=MagicMock()
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"nombre": "Pan", "activo": "true", "disponible": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 404)
        create_cls.return_value.create_producto.assert_not_called()


class PanelCreatePresentacionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_create_presentacion_success_redirects(self) -> None:
        new_row = MagicMock(name="PresentacionRow")
        new_row.id = 300
        path = "/admin/catalog/comercios/1/presentaciones/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_presentacion=MagicMock(return_value=new_row)
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"codigo": "KG", "descripcion": "Bolsa x 1 kg", "activo": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 303)

    def test_create_presentacion_duplicate_codigo_renders_error(self) -> None:
        from backend.services.exceptions import DuplicatePresentacionCodigo

        path = "/admin/catalog/comercios/1/presentaciones/nueva"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(detail=_build_detail())
            create_cls.return_value = _stub_create_service(
                create_presentacion=MagicMock(
                    side_effect=DuplicatePresentacionCodigo("kg")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {"codigo": "KG", "descripcion": "Bolsa x 1 kg", "activo": "true", "orden": "1"},
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ya existe una presentación con ese código", response.text)


class PanelCreatePrecioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_create_precio_success_redirects(self) -> None:
        new_row = MagicMock(name="PrecioRow")
        new_row.id = 900
        pp = CatalogProductoPresentacionRow(
            id=42,
            id_producto=10,
            id_presentacion=200,
            presentacion_descripcion="Bolsa x 1 kg",
            precio_disponible=False,
        )
        path = "/admin/catalog/comercios/1/productos/10/presentaciones/200/precio/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), pp=pp
            )
            create_cls.return_value = _stub_create_service(
                create_precio=MagicMock(return_value=new_row)
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"precio": "150.00"}),
            )
        self.assertEqual(response.status_code, 303)
        create_cls.return_value.create_precio.assert_called_once_with(42, Decimal("150.00"))

    def test_create_precio_invalid_renders_error(self) -> None:
        from backend.services.exceptions import InvalidPrecio

        pp = CatalogProductoPresentacionRow(
            id=42,
            id_producto=10,
            id_presentacion=200,
            presentacion_descripcion="Bolsa x 1 kg",
            precio_disponible=False,
        )
        path = "/admin/catalog/comercios/1/productos/10/presentaciones/200/precio/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), pp=pp
            )
            create_cls.return_value = _stub_create_service(
                create_precio=MagicMock(
                    side_effect=InvalidPrecio("precio must not be negative")
                )
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"precio": "-1.00"}),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("El precio enviado no es válido", response.text)

    def test_create_precio_foreign_comercio_returns_404(self) -> None:
        path = "/admin/catalog/comercios/1/productos/9999/presentaciones/8888/precio/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), pp=None
            )
            create_cls.return_value = _stub_create_service(
                create_precio=MagicMock()
            )
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(path, {"precio": "150.00"}),
            )
        self.assertEqual(response.status_code, 404)
        create_cls.return_value.create_precio.assert_not_called()


class PanelCommerceIsolationTest(unittest.TestCase):
    """The panel must reject nested ids that belong to a foreign
    comercio without ever invoking the create operation."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_foreign_categoria_rendered_as_not_found(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "CatalogCreateService"
        ) as create_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(), categoria=None
            )
            create_cls.return_value = _stub_create_service(
                create_producto=MagicMock()
            )
            response = self.client.get(
                "/admin/catalog/comercios/1/categorias/999/productos/nuevo",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)


class PanelVisualAccessibilityTest(unittest.TestCase):
    """The base template marks up the panel so colour is never the only
    status signal, the keyboard focus ring is visible and no external
    assets are referenced."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def _get_detail(self) -> str:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_focus_ring_visible_in_stylesheet(self) -> None:
        text = self._get_detail()
        self.assertIn("focus-visible", text)
        self.assertIn("--focus-ring", text)

    def test_status_text_appears_for_success_and_error(self) -> None:
        success_text = self._get_detail()
        self.assertIn("success", success_text)
        self.assertIn("error", success_text)

    def test_no_external_assets_referenced(self) -> None:
        text = self._get_detail()
        forbidden_substrings = [
            "https://fonts.googleapis",
            "https://cdn.jsdelivr",
            "https://unpkg.com",
            "<link rel=\"stylesheet\"",
        ]
        for needle in forbidden_substrings:
            self.assertNotIn(needle, text)
        self.assertNotIn("cdn", text.lower())

    def test_responsive_breakpoint_present(self) -> None:
        text = self._get_detail()
        self.assertIn("@media", text)
        self.assertIn("max-width: 800px", text)

    def test_skip_link_present(self) -> None:
        text = self._get_detail()
        self.assertIn("skip-link", text)
        self.assertIn("Saltar al contenido", text)

    def test_status_uses_textual_label_not_colour_alone(self) -> None:
        text = self._get_detail()
        # Visible textual labels exist alongside coloured badges so colour is never the only signal
        self.assertIn("Error", text)
        self.assertIn("badge", text)
        # The base template defines textual outcomes for both success and error states
        self.assertIn("Listo", text)
        self.assertIn("Error", text)

    def test_template_directory_has_no_external_assets(self) -> None:
        template_dir = (
            Path(admin_routes.__file__).resolve().parent.parent
            / "templates"
            / "admin_catalog_panel"
        )
        for entry in template_dir.iterdir():
            if entry.is_file():
                content = entry.read_text(encoding="utf-8")
                self.assertNotIn("cdn", content.lower())
                self.assertNotIn("googleapis", content.lower())
                self.assertNotIn("unpkg", content.lower())


class PanelTableContainmentTest(unittest.TestCase):
    """The payment / delivery sections must contain their tables and
    candidate rows so long cell content cannot push the action
    button outside the visible card.

    The tests look at the rendered markup and the bundled stylesheet
    to verify the containment contract:

    * the payment and delivery tables are wrapped in a
      ``.table-scroll`` container with a ``data-panel-table-scroll``
      marker;
    * the base stylesheet constrains the wrapper to a horizontal
      scroll and forces ``min-width: 0`` on the candidate rows so
      the text block can shrink and wrap;
    * headers remain accessible via ``scope="col"``;
    * the action cell stays visible at the right edge of the table.
    """

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app,
            raise_server_exceptions=False,
            follow_redirects=False,
        )
        _stub_settings_patcher(self)

    def _build_rich_detail(self) -> CommerceDetailView:
        detail = _build_detail()
        return CommerceDetailView(
            id=detail.id,
            nombre_fantasia=detail.nombre_fantasia,
            nombre_corto=detail.nombre_corto,
            razon_social=detail.razon_social,
            cuit=detail.cuit,
            whatsapp=detail.whatsapp,
            calle=detail.calle,
            numero=detail.numero,
            piso_departamento=detail.piso_departamento,
            localidad=detail.localidad,
            provincia=detail.provincia,
            codigo_postal=detail.codigo_postal,
            slug=detail.slug,
            estado=detail.estado,
            zona_horaria=detail.zona_horaria,
            moneda=detail.moneda,
            idioma=detail.idioma,
            medios_pago=detail.medios_pago,
            metodos_entrega=detail.metodos_entrega,
            medios_pago_candidates=[
                CommercePaymentActiveCandidate(
                    id=12,
                    codigo="CANDIDATE",
                    descripcion="Descripción de candidato",
                    habilita_titular=True,
                    habilita_alias=True,
                ),
            ],
            metodos_entrega_candidates=[
                CommerceDeliveryActiveCandidate(
                    id=22,
                    codigo="DELIVERY_CANDIDATE",
                    descripcion="Descripción de candidato de entrega",
                    orden=2,
                ),
            ],
            medios_pago_inactivos=[
                InactivePaymentMethodDetailView(
                    id=13,
                    codigo="MEDIO_INACTIVO",
                    descripcion="Histórico",
                    titular="Titular histórico",
                    alias="alias.historico",
                ),
            ],
            metodos_entrega_inactivos=[
                InactiveDeliveryMethodDetailView(
                    id=23,
                    codigo="ENTREGA_INACTIVA",
                    descripcion="Histórico entrega",
                    orden=3,
                ),
            ],
            flavor=detail.flavor,
        )

    def _get_detail(self) -> str:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=self._build_rich_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        return response.text

    def _base_stylesheet(self) -> str:
        template_dir = (
            Path(admin_routes.__file__).resolve().parent.parent
            / "templates"
            / "admin_catalog_panel"
        )
        base_path = template_dir / "base.html"
        return base_path.read_text(encoding="utf-8")

    def test_payment_table_is_wrapped_in_table_scroll(self) -> None:
        text = self._get_detail()
        self.assertIn(
            'data-panel-table-scroll="medios-pago"',
            text,
        )
        self.assertIn(
            'data-panel-table-scroll="metodos-entrega"',
            text,
        )

    def test_inactive_history_tables_are_wrapped_in_table_scroll(self) -> None:
        text = self._get_detail()
        self.assertIn(
            'data-panel-table-scroll="medios-pago-historico"',
            text,
        )
        self.assertIn(
            'data-panel-table-scroll="metodos-entrega-historico"',
            text,
        )

    def test_table_scroll_wrapper_declares_horizontal_overflow(self) -> None:
        stylesheet = self._base_stylesheet()
        self.assertIn(".table-scroll", stylesheet)
        self.assertIn("overflow-x: auto", stylesheet)
        self.assertIn("overflow-y: hidden", stylesheet)
        self.assertIn("max-width: 100%", stylesheet)

    def test_table_scroll_inner_table_uses_min_width(self) -> None:
        stylesheet = self._base_stylesheet()
        self.assertIn("min-width: 36rem", stylesheet)

    def test_table_cells_force_safe_line_breaks(self) -> None:
        stylesheet = self._base_stylesheet()
        self.assertIn("overflow-wrap: anywhere", stylesheet)
        self.assertIn("word-break: break-word", stylesheet)

    def test_table_header_columns_are_associated_with_scopes(self) -> None:
        text = self._get_detail()
        self.assertIn('<th scope="col"', text)
        self.assertIn('<th scope="col" class="actions-col"', text)

    def test_actions_column_keeps_action_button_visible(self) -> None:
        text = self._get_detail()
        self.assertIn('<td class="actions-col"><a class="button secondary"', text)
        self.assertIn("Configurar</a></td>", text)

    def test_candidate_rows_allow_text_block_to_shrink(self) -> None:
        stylesheet = self._base_stylesheet()
        self.assertIn(".nav-tree-allow-wrap", stylesheet)
        self.assertIn("min-width: 0", stylesheet)
        self.assertIn("flex-wrap: wrap", stylesheet)
        self.assertIn("overflow-wrap: anywhere", stylesheet)
        self.assertIn("word-break: break-word", stylesheet)

    def test_candidate_rows_markup_uses_row_body_class(self) -> None:
        text = self._get_detail()
        self.assertIn('class="row-body"', text)
        self.assertIn('class="button primary row-action"', text)

    def test_action_button_remains_keyboard_accessible(self) -> None:
        text = self._get_detail()
        # The markup keeps the action button as a normal anchor so
        # keyboard activation requires no extra plumbing.
        self.assertIn("<a class=\"button", text)
        self.assertIn(">Configurar</a>", text)


class PanelPrimaryNavMediosPagoTest(unittest.TestCase):
    """The primary navigation in ``base.html`` must surface the
    global payment-method catalog so an operator can reach
    ``/admin/catalog/medios-pago`` (and its ``nuevo`` / ``editar``
    children) without typing the URL."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def _get_medios_pago_view_patch(self) -> MagicMock:
        view_cls = patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        )
        view = view_cls.start()
        view.return_value = _stub_view_service()
        view.return_value.list_global_medios_pago = MagicMock(
            return_value=_build_global_medios_pago_rows()
        )
        view.return_value.get_global_medio_pago = MagicMock(
            return_value=GlobalMedioPagoRow(
                id=1,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                habilita_titular=False,
                habilita_alias=False,
            )
        )
        self.addCleanup(view_cls.stop)
        return view

    def _get_comercios_view_patch(self) -> MagicMock:
        view_cls = patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        )
        view = view_cls.start()
        view.return_value = _stub_view_service(
            detail=_build_detail(),
            catalog=_build_catalog(),
            flavor_options=_build_flavor_options(),
        )
        self.addCleanup(view_cls.stop)
        return view

    def test_medios_pago_link_present_on_list(self) -> None:
        self._get_medios_pago_view_patch()
        response = self.client.get(
            "/admin/catalog/medios-pago",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<a href="/admin/catalog/medios-pago"',
            response.text,
        )
        self.assertIn("Medios de pago", response.text)

    def test_medios_pago_link_is_current_on_list(self) -> None:
        """When the operator is on the list page, the
        ``Medios de pago`` link in the primary nav must be the
        current page (``aria-current="page"``) so the active
        state uses the documented border / background styling."""
        self._get_medios_pago_view_patch()
        response = self.client.get(
            "/admin/catalog/medios-pago",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<a href="/admin/catalog/medios-pago" aria-current="page"',
            response.text,
        )

    def test_medios_pago_link_is_current_on_new_form(self) -> None:
        """The high (``nuevo``) page lives under
        ``/admin/catalog/medios-pago`` so the prefix match must
        also mark the link current there."""
        self._get_medios_pago_view_patch()
        response = self.client.get(
            "/admin/catalog/medios-pago/nuevo",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<a href="/admin/catalog/medios-pago" aria-current="page"',
            response.text,
        )

    def test_medios_pago_link_is_current_on_edit_form(self) -> None:
        """The edit page lives under
        ``/admin/catalog/medios-pago/{id}/editar`` so the prefix
        match must also mark the link current there."""
        self._get_medios_pago_view_patch()
        response = self.client.get(
            "/admin/catalog/medios-pago/1/editar",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<a href="/admin/catalog/medios-pago" aria-current="page"',
            response.text,
        )

    def test_medios_pago_link_not_current_on_comercios_section(self) -> None:
        """When the operator is anywhere under
        ``/admin/catalog/comercios`` the ``Medios de pago`` link
        must NOT carry ``aria-current="page"``; only the
        ``Comercios`` link should. This guards the prefix match
        against accidentally highlighting the wrong entry."""
        self._get_comercios_view_patch()
        response = self.client.get(
            "/admin/catalog/comercios",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            '<a href="/admin/catalog/medios-pago" aria-current="page"',
            response.text,
        )
        self.assertIn(
            '<a href="/admin/catalog/comercios" aria-current="page"',
            response.text,
        )

    def test_comercios_link_not_current_on_medios_pago_section(self) -> None:
        """``/admin/catalog/medios-pago`` is NOT a sub-path of
        ``/admin/catalog/comercios`` so the ``Comercios`` link
        must lose its current state once the operator navigates
        to the medios-pago section. The two primary-nav entries
        are siblings, not nested."""
        self._get_medios_pago_view_patch()
        response = self.client.get(
            "/admin/catalog/medios-pago",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            '<a href="/admin/catalog/comercios" aria-current="page"',
            response.text,
        )


class PanelCsrfNonceTest(unittest.TestCase):
    def test_panel_form_nonce_is_deterministic_and_path_bound(self) -> None:
        from backend.dependencies import (
            compute_panel_form_nonce,
            resolve_panel_csrf_secret,
        )

        secret = resolve_panel_csrf_secret()
        nonce_a = compute_panel_form_nonce(path="/admin/catalog/comercios/1/flavor", secret=secret)
        nonce_b = compute_panel_form_nonce(path="/admin/catalog/comercios/1/flavor", secret=secret)
        nonce_c = compute_panel_form_nonce(path="/admin/catalog/comercios/1/categorias/nueva", secret=secret)
        self.assertEqual(nonce_a, nonce_b)
        self.assertNotEqual(nonce_a, nonce_c)
        self.assertEqual(len(nonce_a), 64)


class PanelNoSessionOrCommerceLeakageTest(unittest.TestCase):
    """The panel must not produce or persist server-side state: no
    cookies, no session storage, no token URL parameters and no
    comercio cross-lookup."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_no_cookie_or_session_header_on_success(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=_build_detail(),
                catalog=_build_catalog(),
                flavor_options=_build_flavor_options(),
            )
            response = self.client.get(
                "/admin/catalog/comercios/1",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("set-cookie", {k.lower() for k in response.headers})
        self.assertNotIn("token=", response.text.lower())


def _build_global_medios_pago_rows() -> list[GlobalMedioPagoRow]:
    return [
        GlobalMedioPagoRow(
            id=1,
            codigo="EFECTIVO",
            descripcion="Efectivo",
            activo=True,
            habilita_titular=False,
            habilita_alias=False,
        ),
        GlobalMedioPagoRow(
            id=2,
            codigo="TRANSFERENCIA",
            descripcion="Transferencia",
            activo=True,
            habilita_titular=True,
            habilita_alias=True,
        ),
        GlobalMedioPagoRow(
            id=3,
            codigo="MERCADOPAGO",
            descripcion="MercadoPago",
            activo=False,
            habilita_titular=False,
            habilita_alias=True,
        ),
    ]


class PanelGlobalMediosPagoListTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_list_renders_all_rows_with_flags(self) -> None:
        rows = _build_global_medios_pago_rows()
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service()
            service_cls.return_value.list_global_medios_pago = MagicMock(return_value=rows)
            response = self.client.get(
                "/admin/catalog/medios-pago",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Medios de pago globales", response.text)
        self.assertIn("EFECTIVO", response.text)
        self.assertIn("TRANSFERENCIA", response.text)
        self.assertIn("MERCADOPAGO", response.text)
        # Independent flags must be readable on the rendered row
        self.assertIn("habilita_titular", response.text.lower())
        self.assertIn("habilita_alias", response.text.lower())

    def test_list_without_auth_returns_401(self) -> None:
        response = self.client.get("/admin/catalog/medios-pago")
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_list_does_not_invoke_json_api(self) -> None:
        """The panel must call the view service directly, not the
        JSON API through internal HTTP."""
        rows = _build_global_medios_pago_rows()
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as medios_service_cls:
            view_cls.return_value = _stub_view_service()
            view_cls.return_value.list_global_medios_pago = MagicMock(return_value=rows)
            medios_service_cls.return_value = MagicMock(name="MediosPagoService")
            response = self.client.get(
                "/admin/catalog/medios-pago",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        view_cls.return_value.list_global_medios_pago.assert_called_once()
        medios_service_cls.return_value.list_all.assert_not_called()


class PanelGlobalMediosPagoNewFormTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_new_form_renders_with_default_flags_false(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls:
            view_cls.return_value = _stub_view_service()
            response = self.client.get(
                "/admin/catalog/medios-pago/nuevo",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        # The checkboxes for the two flags must be present
        self.assertIn('name="habilita_titular"', response.text)
        self.assertIn('name="habilita_alias"', response.text)
        self.assertIn('name="activo"', response.text)
        # The CSRF nonce field must be bound to the new-form POST target
        expected_nonce = compute_panel_form_nonce(
            path="/admin/catalog/medios-pago/nuevo",
            secret=resolve_panel_csrf_secret(),
        )
        self.assertIn(
            f'name="{NONCE_FIELD}" value="{expected_nonce}"',
            response.text,
        )


class PanelGlobalMediosPagoCreateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_create_calls_service_with_both_flags(self) -> None:
        path = "/admin/catalog/medios-pago/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            new_row = MagicMock(name="NewMedioPago", id=42)
            service_cls.return_value.create.return_value = new_row
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {
                        "codigo": "  TEST_MEDIO  ",
                        "descripcion": "  Test medio  ",
                        "activo": "true",
                        "habilita_titular": "true",
                        "habilita_alias": "false",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)
        service_cls.return_value.create.assert_called_once_with(
            codigo="  TEST_MEDIO  ",
            descripcion="  Test medio  ",
            activo=True,
            habilita_titular=True,
            habilita_alias=False,
        )

    def test_create_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/medios-pago/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data={
                    "codigo": "TEST",
                    "descripcion": "Test",
                    "activo": "true",
                },
            )
        self.assertEqual(response.status_code, 400)
        service_cls.return_value.create.assert_not_called()

    def test_create_without_origin_is_rejected(self) -> None:
        path = "/admin/catalog/medios-pago/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            response = self.client.post(
                path,
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
                data=_csrf_form_data(
                    path,
                    {
                        "codigo": "TEST",
                        "descripcion": "Test",
                        "activo": "true",
                    },
                ),
            )
        self.assertEqual(response.status_code, 400)
        service_cls.return_value.create.assert_not_called()

    def test_create_with_cross_origin_is_rejected(self) -> None:
        path = "/admin/catalog/medios-pago/nuevo"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    "Origin": "https://malicious.example.com",
                },
                data=_csrf_form_data(
                    path,
                    {
                        "codigo": "TEST",
                        "descripcion": "Test",
                        "activo": "true",
                    },
                ),
            )
        self.assertEqual(response.status_code, 400)
        service_cls.return_value.create.assert_not_called()


class PanelGlobalMediosPagoEditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self.override = _install_session_override(self, self.app, self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        _stub_settings_patcher(self)

    def test_edit_form_renders_existing_flags(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service()
            service_cls.return_value.get_global_medio_pago = MagicMock(
                return_value=GlobalMedioPagoRow(
                    id=2,
                    codigo="TRANSFERENCIA",
                    descripcion="Transferencia",
                    activo=True,
                    habilita_titular=True,
                    habilita_alias=False,
                )
            )
            response = self.client.get(
                "/admin/catalog/medios-pago/2/editar",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("TRANSFERENCIA", response.text)
        self.assertIn('name="habilita_titular"', response.text)
        self.assertIn('name="habilita_alias"', response.text)
        expected_nonce = compute_panel_form_nonce(
            path="/admin/catalog/medios-pago/2/editar",
            secret=resolve_panel_csrf_secret(),
        )
        self.assertIn(
            f'name="{NONCE_FIELD}" value="{expected_nonce}"',
            response.text,
        )

    def test_edit_form_404_when_unknown(self) -> None:
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service()
            service_cls.return_value.get_global_medio_pago = MagicMock(return_value=None)
            response = self.client.get(
                "/admin/catalog/medios-pago/9999/editar",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)

    def test_edit_form_400_when_invalid_id(self) -> None:
        response = self.client.get(
            "/admin/catalog/medios-pago/abc/editar",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 400)

    def test_update_calls_service_with_partial_payload(self) -> None:
        path = "/admin/catalog/medios-pago/2/editar"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            service_cls.return_value.get_by_id.return_value = MagicMock(
                id=2,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                activo=True,
                habilita_titular=True,
                habilita_alias=False,
            )
            service_cls.return_value.update.return_value = MagicMock(id=2)
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {
                        "descripcion": "  Transferencia bancaria  ",
                        "activo": "false",
                        "habilita_titular": "true",
                        "habilita_alias": "true",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)
        service_cls.return_value.update.assert_called_once_with(
            2,
            descripcion="  Transferencia bancaria  ",
            activo=False,
            habilita_titular=True,
            habilita_alias=True,
        )

    def test_edit_form_renders_hidden_false_inputs_before_checkbox(self) -> None:
        """The edit template must render a hidden ``value="false"``
        input BEFORE every boolean checkbox. Starlette's
        ``FormData`` keeps the LAST occurrence of a duplicated key
        (the underlying dict comprehension overwrites earlier
        values), so a hidden ``false`` placed AFTER the checkbox
        would win over the ``true`` value the browser sends for a
        checked box and silently persist ``False`` even when the
        operator marked the field on. Placing the hidden input
        BEFORE the checkbox keeps the checkbox value last in the
        form payload so the checked state survives the round trip."""
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service()
            service_cls.return_value.get_global_medio_pago = MagicMock(
                return_value=GlobalMedioPagoRow(
                    id=2,
                    codigo="TRANSFERENCIA",
                    descripcion="Transferencia",
                    activo=True,
                    habilita_titular=True,
                    habilita_alias=True,
                )
            )
            response = self.client.get(
                "/admin/catalog/medios-pago/2/editar",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        for field in ("activo", "habilita_titular", "habilita_alias"):
            with self.subTest(field=field):
                hidden_idx = response.text.index(
                    f'name="{field}" value="false"'
                )
                checkbox_idx = response.text.index(
                    f'name="{field}" type="checkbox"', hidden_idx
                )
                self.assertLess(
                    hidden_idx,
                    checkbox_idx,
                    f"hidden false input for {field!r} must come BEFORE the checkbox",
                )

    def test_new_form_does_not_render_hidden_false_inputs(self) -> None:
        """The new-form path keeps the documented absence-as-default
        contract for ``activo``: the operator only sees the
        checkbox and the create route falls back to the documented
        default when the field is absent. The hidden ``false``
        siblings are edit-only so the create semantics stay
        untouched."""
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as service_cls:
            service_cls.return_value = _stub_view_service()
            response = self.client.get(
                "/admin/catalog/medios-pago/nuevo",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        for field in ("activo", "habilita_titular", "habilita_alias"):
            with self.subTest(field=field):
                self.assertNotIn(
                    f'name="{field}" value="false"',
                    response.text,
                )

    def test_update_checked_checkbox_persists_true_in_browser_order(self) -> None:
        """Submitting the real edit form with every checkbox
        marked must persist ``True`` for each boolean field. The
        test sends the realistic browser payload: the hidden
        ``false`` sibling (rendered first by the template) appears
        before the checked ``true`` value in the body, exactly as
        Starlette parses it. This is the regression that motivated
        the current fix: a hidden ``false`` placed AFTER the
        checkbox would overwrite the checked ``true`` value because
        ``FormData`` keeps the LAST occurrence."""
        path = "/admin/catalog/medios-pago/2/editar"
        nonce = compute_panel_form_nonce(
            path=path, secret=resolve_panel_csrf_secret()
        )
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            service_cls.return_value.get_by_id.return_value = MagicMock(
                id=2,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                activo=False,
                habilita_titular=False,
                habilita_alias=False,
            )
            service_cls.return_value.update.return_value = MagicMock(id=2)
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                # ``data`` carries each boolean field twice in the
                # exact browser order: the hidden ``false`` sibling
                # first (rendered before the checkbox by the
                # template), then the checked ``true`` value. The
                # body encodes as
                # ``activo=false&activo=true&...``.
                data={
                    NONCE_FIELD: nonce,
                    "descripcion": "Transferencia",
                    "activo": ["false", "true"],
                    "habilita_titular": ["false", "true"],
                    "habilita_alias": ["false", "true"],
                },
            )
        self.assertEqual(response.status_code, 303)
        service_cls.return_value.update.assert_called_once_with(
            2,
            descripcion="Transferencia",
            activo=True,
            habilita_titular=True,
            habilita_alias=True,
        )

    def test_update_with_all_checkboxes_unchecked_persists_false(self) -> None:
        """Submitting the real edit form with every checkbox
        unchecked must persist ``False`` for each boolean field. The
        browser only sends the hidden ``false`` sibling when the
        checkbox is unchecked (the unchecked checkbox itself is
        omitted from the payload), so the body carries a single
        ``false`` value per field."""
        path = "/admin/catalog/medios-pago/2/editar"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            service_cls.return_value.get_by_id.return_value = MagicMock(
                id=2,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                activo=True,
                habilita_titular=True,
                habilita_alias=True,
            )
            service_cls.return_value.update.return_value = MagicMock(id=2)
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {
                        "descripcion": "Transferencia",
                        "activo": "false",
                        "habilita_titular": "false",
                        "habilita_alias": "false",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)
        service_cls.return_value.update.assert_called_once_with(
            2,
            descripcion="Transferencia",
            activo=False,
            habilita_titular=False,
            habilita_alias=False,
        )

    def test_update_mixed_checkbox_states_persists_correctly(self) -> None:
        """A mixed form with one checkbox unchecked and the other
        two marked must persist ``False`` for the unchecked field
        and ``True`` for the marked ones. The test sends the
        realistic browser payload per field so the duplicate-value
        behaviour (checked) and the single-value behaviour
        (unchecked) coexist in the same submission. This guards
        against a future regression where the hidden-input ordering
        could silently flip one of the booleans."""
        path = "/admin/catalog/medios-pago/2/editar"
        nonce = compute_panel_form_nonce(
            path=path, secret=resolve_panel_csrf_secret()
        )
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            service_cls.return_value.get_by_id.return_value = MagicMock(
                id=2,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                activo=False,
                habilita_titular=True,
                habilita_alias=True,
            )
            service_cls.return_value.update.return_value = MagicMock(id=2)
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data={
                    NONCE_FIELD: nonce,
                    "descripcion": "  Transferencia bancaria  ",
                    # ``activo`` is marked: hidden sibling + checkbox
                    "activo": ["false", "true"],
                    # ``habilita_titular`` is unchecked: only the
                    # hidden ``false`` sibling survives
                    "habilita_titular": "false",
                    # ``habilita_alias`` is marked: hidden sibling + checkbox
                    "habilita_alias": ["false", "true"],
                },
            )
        self.assertEqual(response.status_code, 303)
        service_cls.return_value.update.assert_called_once_with(
            2,
            descripcion="  Transferencia bancaria  ",
            activo=True,
            habilita_titular=False,
            habilita_alias=True,
        )

    def test_update_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/medios-pago/2/editar"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data={
                    "descripcion": "X",
                    "habilita_titular": "true",
                },
            )
        self.assertEqual(response.status_code, 400)
        service_cls.return_value.update.assert_not_called()

    def test_update_404_when_unknown(self) -> None:
        path = "/admin/catalog/medios-pago/9999/editar"
        with patch.object(
            admin_routes, "AdministrativeCatalogPanelViewService"
        ) as view_cls, patch.object(
            admin_routes, "MediosPagoService"
        ) as service_cls:
            view_cls.return_value = _stub_view_service()
            service_cls.return_value.update.side_effect = admin_routes.MediosPagoNotFound(9999)
            response = self.client.post(
                path,
                headers={
                    **_basic_auth_header("any", CONFIGURED_TOKEN),
                    **_same_origin_headers(),
                },
                data=_csrf_form_data(
                    path,
                    {
                        "descripcion": "X",
                        "habilita_titular": "true",
                    },
                ),
            )
        self.assertEqual(response.status_code, 404)


class PanelGlobalMediosPagoJsonBoundaryTest(unittest.TestCase):
    """The new panel surface must not weaken the JSON API
    authentication contract: the JSON endpoints still require
    ``X-Admin-Token`` and the panel never calls them through
    internal HTTP."""

    def setUp(self) -> None:
        self.app = main_module.app
        self.client = TestClient(self.app, raise_server_exceptions=False, follow_redirects=False)
        self.session = MagicMock(name="DatabaseSession")
        self.override = _install_session_override(self, self.app, self.session)
        _stub_settings_patcher(self)

    def test_json_get_rejects_basic_auth(self) -> None:
        response = self.client.get(
            "/medios-pago/1",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 401)
        self.override.assert_not_called()

    def test_json_create_requires_x_admin_token(self) -> None:
        response = self.client.post(
            "/medios-pago",
            json={
                "codigo": "TEST_TOKEN",
                "descripcion": "Test token",
            },
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
