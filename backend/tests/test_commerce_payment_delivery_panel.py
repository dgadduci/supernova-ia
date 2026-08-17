"""Focused tests for the new commerce payment/delivery configuration routes.

The tests cover the documented HTML adapter the OpenSpec change
authorises:

* Browser Basic authentication.
* Path-bound CSRF nonce — including the new mutation paths.
* Same-origin validation for every state-changing submission.
* Escaped errors autoescaped by the Jinja templates.
* Redirect-after-POST to the exact commerce detail page.
* Field availability for ``titular`` / ``alias`` render-only when
  the global flag is disabled.
* Commerce isolation: a foreign association id cannot mutate
  another comercio's bridge row.
* Service exception mapping — InvalidPaymentField /
  InvalidDeliveryOrden / MetodoEntregaNotFound round-trip to
  the documented HTTP status code.
"""
from __future__ import annotations

import base64
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.admin.routes as admin_routes
import backend.dependencies as dependencies_module
from backend.admin.views import (
    CommerceDeliveryActiveCandidate,
    CommerceDetailView,
    CommercePaymentActiveCandidate,
    CommerceSummary,
    DeliveryMethodConfigurationView,
    DeliveryMethodDetailView,
    FlavorOption,
    FlavorSummaryView,
    GlobalMedioPagoRow,
    GlobalMetodoEntregaRow,
    InactiveDeliveryMethodDetailView,
    InactivePaymentMethodDetailView,
    PaymentMethodConfigurationView,
    PaymentMethodDetailView,
)
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import (
    PANEL_FORM_NONCE_FIELD,
    compute_panel_form_nonce,
    get_session,
    resolve_panel_csrf_secret,
)
from backend.services.exceptions import (
    InvalidDeliveryOrden,
    InvalidPaymentField,
    MetodoEntregaNotFound,
)

CONFIGURED_TOKEN = "admin-panel-token-for-tests"
NONCE_FIELD = PANEL_FORM_NONCE_FIELD
TESTCLIENT_ORIGIN = "http://testserver"


def _settings(**overrides: object) -> Settings:
    base = settings_module.load_settings()
    payload = {**base.__dict__, "order_management_admin_token": CONFIGURED_TOKEN}
    payload["admin_panel_csrf_secret"] = None
    payload["admin_panel_allowed_origin"] = None
    payload.update(overrides)
    return Settings(**payload)


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _csrf_form_data(path: str, extra: dict[str, str]) -> dict[str, str]:
    nonce = compute_panel_form_nonce(
        path=path, secret=resolve_panel_csrf_secret()
    )
    return {NONCE_FIELD: nonce, **extra}


def _same_origin_headers() -> dict[str, str]:
    return {"Origin": TESTCLIENT_ORIGIN}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
    return app


class _SessionStub:
    def __init__(self, value: object) -> None:
        self.value = value
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
        return self.value


def _install_session_override(
    test: unittest.TestCase, app: FastAPI, session: object
) -> _SessionStub:
    stub = _SessionStub(session)
    app.dependency_overrides[get_session] = stub
    test.addCleanup(app.dependency_overrides.clear)
    return stub


def _stub_settings(test: unittest.TestCase) -> None:
    patcher = patch.object(
        dependencies_module, "load_settings", return_value=_settings()
    )
    patcher.start()
    test.addCleanup(patcher.stop)


def _stub_view_service(
    *,
    detail: object | None = None,
    global_medio_pago: object | None = None,
    global_metodo_entrega: object | None = None,
    payment_configuration: object | None = None,
    delivery_configuration: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        get_commerce_detail=MagicMock(return_value=detail),
        get_global_medio_pago=MagicMock(return_value=global_medio_pago),
        get_commerce_payment_configuration=MagicMock(
            return_value=payment_configuration
        ),
        get_commerce_delivery_configuration=MagicMock(
            return_value=delivery_configuration
        ),
        get_global_metodo_entrega=MagicMock(
            return_value=global_metodo_entrega
        ),
    )


def _stub_config_service(
    *,
    enable_payment: object | None = None,
    disable_payment: object | None = None,
    enable_delivery: object | None = None,
    disable_delivery: object | None = None,
    update_delivery: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        enable_payment_for_comercio=MagicMock(return_value=enable_payment),
        disable_payment_for_comercio=MagicMock(return_value=disable_payment),
        enable_delivery_for_comercio=MagicMock(return_value=enable_delivery),
        disable_delivery_for_comercio=MagicMock(return_value=disable_delivery),
        update_delivery_order_for_comercio=MagicMock(return_value=update_delivery),
    )


def _build_detail() -> CommerceDetailView:
    return CommerceDetailView(
        id=1,
        nombre_fantasia="Comercio X",
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
                association_id=110,
                medio_pago_id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                titular=None,
                alias=None,
            ),
        ],
        metodos_entrega=[
            DeliveryMethodDetailView(
                association_id=120,
                metodo_entrega_id=20,
                codigo="RETIRO",
                descripcion="Retiro en local",
                activo=True,
                orden=1,
            ),
        ],
        medios_pago_candidates=[
            CommercePaymentActiveCandidate(
                id=11,
                codigo="TRANSFERENCIA",
                descripcion="Transferencia",
                habilita_titular=True,
                habilita_alias=True,
            ),
        ],
        metodos_entrega_candidates=[
            CommerceDeliveryActiveCandidate(
                id=21,
                codigo="DELIVERY",
                descripcion="Envío a domicilio",
                orden=2,
            ),
        ],
        medios_pago_inactivos=[
            InactivePaymentMethodDetailView(
                id=12,
                codigo="MP_INACTIVO",
                descripcion="Histórico",
                titular="Titular histórico",
                alias="alias.historico",
            ),
        ],
        metodos_entrega_inactivos=[
            InactiveDeliveryMethodDetailView(
                id=22,
                codigo="DELIVERY_INACTIVO",
                descripcion="Histórico",
                orden=3,
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


class PaymentFormAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def test_get_form_requires_basic_auth(self) -> None:
        response = self.client.get("/admin/catalog/comercios/1/medios-pago/10")
        self.assertEqual(response.status_code, 401)

    def test_post_requires_basic_auth(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        response = self.client.post(
            path,
            data={NONCE_FIELD: "x", "action": "enable"},
        )
        self.assertEqual(response.status_code, 401)


class PaymentFormCsrfTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_post_without_nonce_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data={"action": "enable"},
            )
        self.assertEqual(response.status_code, 400)
        config_cls.return_value.enable_payment_for_comercio.assert_not_called()

    def test_post_without_origin_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
                data=_csrf_form_data(path, {"action": "enable"}),
            )
        self.assertEqual(response.status_code, 400)
        config_cls.return_value.enable_payment_for_comercio.assert_not_called()

    def test_post_with_other_route_nonce_is_rejected(self) -> None:
        target = "/admin/catalog/comercios/1/medios-pago/10"
        other = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                target,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    other, {"action": "enable"}
                ),
            )
        self.assertEqual(response.status_code, 400)
        config_cls.return_value.enable_payment_for_comercio.assert_not_called()


class PaymentFormHappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_enable_post_redirects_to_commerce_detail(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = _stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {
                        "action": "enable",
                        "titular": "TITULAR",
                        "alias": "alias.x",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/admin/catalog/comercios/1",
        )
        config_cls.return_value.enable_payment_for_comercio.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular="TITULAR",
            alias="alias.x",
        )

    def test_disable_post_redirects_to_commerce_detail(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = _stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(path, {"action": "disable"}),
            )
        self.assertEqual(response.status_code, 303)
        config_cls.return_value.disable_payment_for_comercio.assert_called_once_with(
            comercio_id=1, medio_pago_id=10
        )

    def test_invalid_payment_field_renders_form_with_error(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            detail = _build_detail()
            global_row = GlobalMedioPagoRow(
                id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                habilita_titular=False,
                habilita_alias=False,
            )
            configuration = PaymentMethodConfigurationView(
                association_id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                titular="Original",
                alias="original.alias",
                habilita_titular=False,
                habilita_alias=False,
            )
            view_cls.return_value = _stub_view_service(
                detail=detail,
                global_medio_pago=global_row,
                payment_configuration=configuration,
            )
            config_cls.return_value = _stub_config_service()
            config_cls.return_value.enable_payment_for_comercio.side_effect = InvalidPaymentField(
                "alias cannot be set when the global method disables it"
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {
                        "action": "enable",
                        "titular": "Original",
                        "alias": "forged.alias",
                    },
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("alias", response.text.lower())
        self.assertIn("catálogo global", response.text.lower())


class PaymentFormReactivationTest(unittest.TestCase):
    """Re-activation of an existing association must NOT include the
    disabled fields in the POST payload so the service accepts the
    request and preserves the historical values for ``titular`` /
    ``alias`` even when the global flags are disabled.
    """

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)
        self.detail = _build_detail()
        self.global_row = GlobalMedioPagoRow(
            id=10,
            codigo="EFECTIVO",
            descripcion="Efectivo",
            activo=True,
            habilita_titular=False,
            habilita_alias=False,
        )
        self.configuration = PaymentMethodConfigurationView(
            association_id=110,
            codigo="EFECTIVO",
            descripcion="Efectivo",
            activo=False,
            titular="PRESERVED_TITULAR",
            alias="preserved.alias",
            habilita_titular=False,
            habilita_alias=False,
        )

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_get_form_omits_hidden_inputs_for_disabled_fields(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=self.detail,
                global_medio_pago=self.global_row,
                payment_configuration=self.configuration,
            )
            response = self.client.get(
                path,
                headers=self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'action="/admin/catalog/comercios/1/medios-pago/10"',
            response.text,
        )
        self.assertNotIn(
            'action="/admin/catalog/comercios/1/medios-pago/110"',
            response.text,
        )
        self.assertNotIn('name="titular"', response.text)
        self.assertNotIn('name="alias"', response.text)
        self.assertIn("valor previo se conserva", response.text)

    def test_post_without_disabled_fields_reactivates_preserving_history(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = _stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(path, {"action": "enable"}),
            )
        self.assertEqual(response.status_code, 303)
        config_cls.return_value.enable_payment_for_comercio.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

    def test_post_with_tampered_disabled_field_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            detail = _build_detail()
            global_row = GlobalMedioPagoRow(
                id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                habilita_titular=False,
                habilita_alias=False,
            )
            configuration = PaymentMethodConfigurationView(
                association_id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=False,
                titular="PRESERVED_TITULAR",
                alias="preserved.alias",
                habilita_titular=False,
                habilita_alias=False,
            )
            view_cls.return_value = _stub_view_service(
                detail=detail,
                global_medio_pago=global_row,
                payment_configuration=configuration,
            )
            config_cls.return_value = _stub_config_service()
            config_cls.return_value.enable_payment_for_comercio.side_effect = InvalidPaymentField(
                "alias cannot be set when the global method disables it"
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {
                        "action": "enable",
                        "alias": "forged.alias",
                    },
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("catálogo global", response.text.lower())


class DeliveryFormValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)
        self.detail = _build_detail()
        self.delivery_configuration = DeliveryMethodConfigurationView(
            association_id=0,
            codigo="DELIVERY",
            descripcion="Envío a domicilio",
            activo=False,
            orden=0,
            global_orden=2,
        )
        self.delivery_global = GlobalMetodoEntregaRow(
            id=20,
            codigo="DELIVERY",
            descripcion="Envío a domicilio",
            activo=True,
            orden=2,
        )

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _stub_view_service(self) -> SimpleNamespace:
        return _stub_view_service(
            detail=self.detail,
            delivery_configuration=self.delivery_configuration,
            global_metodo_entrega=self.delivery_global,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_existing_association_opens_form_with_global_id(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        configuration = DeliveryMethodConfigurationView(
            association_id=120,
            codigo="DELIVERY",
            descripcion="Envío a domicilio",
            activo=True,
            orden=2,
            global_orden=2,
        )
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=self.detail,
                delivery_configuration=configuration,
                global_metodo_entrega=self.delivery_global,
            )
            response = self.client.get(path, headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'action="/admin/catalog/comercios/1/metodos-entrega/20"',
            response.text,
        )
        self.assertNotIn(
            'action="/admin/catalog/comercios/1/metodos-entrega/120"',
            response.text,
        )

    def test_active_global_method_enables_habilitar_button(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls:
            view_cls.return_value = self._stub_view_service()
            response = self.client.get(path, headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn("Habilitar", response.text)
        self.assertNotIn('disabled aria-disabled="true"', response.text)
        view_cls.return_value.get_global_metodo_entrega.assert_called_once_with(20)

    def test_error_rerender_preserves_active_global_method(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path, {"action": "enable", "orden": "abc"}
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Habilitar", response.text)
        self.assertNotIn('disabled aria-disabled="true"', response.text)
        view_cls.return_value.get_global_metodo_entrega.assert_called_once_with(20)

    def test_inactive_global_method_cannot_be_enabled(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        inactive_global = GlobalMetodoEntregaRow(
            id=20,
            codigo="DELIVERY",
            descripcion="Envío a domicilio",
            orden=2,
            activo=False,
        )
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls:
            view_cls.return_value = _stub_view_service(
                detail=self.detail,
                delivery_configuration=self.delivery_configuration,
                global_metodo_entrega=inactive_global,
            )
            response = self.client.get(path, headers=self._auth_headers())
        self.assertEqual(response.status_code, 404)

    def test_enable_without_orden_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(path, {"action": "enable"}),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("orden", response.text.lower())
        config_cls.return_value.enable_delivery_for_comercio.assert_not_called()

    def test_enable_with_negative_orden_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            config_cls.return_value.enable_delivery_for_comercio.side_effect = InvalidDeliveryOrden(
                "orden must be a non-negative integer"
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path, {"action": "enable", "orden": "-1"}
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("orden", response.text.lower())

    def test_enable_with_non_integer_orden_is_rejected(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path, {"action": "enable", "orden": "abc"}
                ),
            )
        self.assertEqual(response.status_code, 200)
        config_cls.return_value.enable_delivery_for_comercio.assert_not_called()

    def test_enable_with_valid_orden_redirects(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path, {"action": "enable", "orden": "3"}
                ),
            )
        self.assertEqual(response.status_code, 303)
        config_cls.return_value.enable_delivery_for_comercio.assert_called_once_with(
            comercio_id=1, metodo_entrega_id=20, orden=3
        )

    def test_metodo_not_found_renders_not_found(self) -> None:
        path = "/admin/catalog/comercios/1/metodos-entrega/20"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = self._stub_view_service()
            config_cls.return_value = _stub_config_service()
            config_cls.return_value.enable_delivery_for_comercio.side_effect = MetodoEntregaNotFound(
                20
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path, {"action": "enable", "orden": "1"}
                ),
            )
        self.assertEqual(response.status_code, 404)


class CommerceIsolationPanelTest(unittest.TestCase):
    """The panel must never resolve a foreign commerce association."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_post_uses_path_comercio_id_only(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            view_cls.return_value = _stub_view_service()
            config_cls.return_value = _stub_config_service()
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {
                        "action": "enable",
                        "titular": "TITULAR",
                        "alias": "alias.x",
                    },
                ),
            )
        self.assertEqual(response.status_code, 303)
        config_cls.return_value.enable_payment_for_comercio.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular="TITULAR",
            alias="alias.x",
        )


class PaymentFormXssEscapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.app = _build_app()
        self._install_session_override(self, self.app, self.session)
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )
        _stub_settings(self)

    @staticmethod
    def _install_session_override(test, app, session):
        stub = _SessionStub(session)
        app.dependency_overrides[get_session] = stub
        test.addCleanup(app.dependency_overrides.clear)
        return stub

    def _auth_headers(self) -> dict[str, str]:
        return {
            **_basic_auth_header("any", CONFIGURED_TOKEN),
            **_same_origin_headers(),
        }

    def test_invalid_payment_field_message_is_escaped(self) -> None:
        path = "/admin/catalog/comercios/1/medios-pago/10"
        with patch.object(
            admin_routes,
            "AdministrativeCatalogPanelViewService",
        ) as view_cls, patch.object(
            admin_routes,
            "CommercePaymentDeliveryConfigurationService",
        ) as config_cls:
            detail = _build_detail()
            global_row = GlobalMedioPagoRow(
                id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                habilita_titular=True,
                habilita_alias=False,
            )
            configuration = PaymentMethodConfigurationView(
                association_id=10,
                codigo="EFECTIVO",
                descripcion="Efectivo",
                activo=True,
                titular="<script>alert(1)</script>",
                alias=None,
                habilita_titular=True,
                habilita_alias=False,
            )
            view_cls.return_value = _stub_view_service(
                detail=detail,
                global_medio_pago=global_row,
                payment_configuration=configuration,
            )
            config_cls.return_value = _stub_config_service()
            config_cls.return_value.enable_payment_for_comercio.side_effect = InvalidPaymentField(
                "alias cannot be set when the global method disables it"
            )
            response = self.client.post(
                path,
                headers=self._auth_headers(),
                data=_csrf_form_data(
                    path,
                    {
                        "action": "enable",
                        "titular": "<script>alert(1)</script>",
                        "alias": "forged",
                    },
                ),
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>alert(1)</script>", response.text)


if __name__ == "__main__":
    unittest.main()
