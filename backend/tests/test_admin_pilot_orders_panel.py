"""Focused tests for the pilot order operations panel router.

These tests cover the panel-only HTTP Basic authentication, the
bounded list view, the exact-detail view, the provider-history
projection, the template escaping rules and the strict no-mutation
contract for the panel surface. They use a stub SQLAlchemy session
and a stubbed :class:`PilotOrderOperationsViewService` so no real
database is touched.

The tests run against a ``FastAPI`` test app that wires the panel
router alone, with the existing ``backend.dependencies.get_session``
overridden through a no-argument callable (FastAPI's introspection
rejects ``MagicMock`` as a dependency).
"""
from __future__ import annotations

import base64
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routers.admin_pilot_orders as router_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import get_session
from backend.models import EstadoPedido, EstadoSession
from backend.services.pilot_order_operations_view_service import (
    ClientSummary,
    CommerceSummary,
    DeliveryMethodView,
    OrderDetailView,
    OrderLineView,
    OrderListRow,
    OrderListView,
    OrderSummary,
    OutboundMessageView,
    PaymentMethodView,
    ProviderHistoryEntry,
    ProviderHistoryView,
    ProviderReceiptView,
    SessionSummary,
    format_local_datetime,
)

CONFIGURED_TOKEN = "pilot-panel-token-for-tests"


def _settings(token: str | None = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(
        **{**base.__dict__, "order_management_admin_token": token}
    )


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router)
    return app


def _override_session_with(_: object) -> object:
    return None


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


def _stub_service(
    *,
    list_view: OrderListView | None = None,
    detail: OrderDetailView | None = None,
    history: ProviderHistoryView | None = None,
):
    return SimpleNamespace(
        list_orders=MagicMock(return_value=list_view),
        get_detail=MagicMock(return_value=detail),
        get_provider_history=MagicMock(return_value=history),
    )


def _build_detail() -> OrderDetailView:
    base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    zona = "America/Argentina/Buenos_Aires"
    return OrderDetailView(
        pedido=OrderSummary(
            id=42,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=base,
            fecha_alta_local=format_local_datetime(base, zona),
            fecha_ultima_modificacion=base,
            fecha_ultima_modificacion_local=format_local_datetime(base, zona),
        ),
        session=SessionSummary(
            id=21,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=base,
            datetime_inicio_local=format_local_datetime(base, zona),
            datetime_ultimo_movimiento=base,
            datetime_ultimo_movimiento_local=format_local_datetime(base, zona),
        ),
        client=ClientSummary(
            id=31,
            nombre="Ana & <script>",
            whatsapp="+5491100000001",
            activo=True,
        ),
        commerce=CommerceSummary(
            id=1,
            nombre_fantasia="Comercio & 'A'",
            nombre_corto="A",
            zona_horaria=zona,
        ),
        direccion_entrega="Calle 123 & <b>",
        observaciones="Llamar & <i>",
        datetime_entrega_programada=None,
        datetime_entrega_programada_local=None,
        medio_pago=PaymentMethodView(id=7, descripcion="Efectivo"),
        metodo_entrega=DeliveryMethodView(id=8, descripcion="Retiro"),
        lineas=[
            OrderLineView(
                id=100,
                producto_nombre="Pan <b>",
                presentacion_descripcion="Bolsa x 1kg",
                cantidad=2,
                precio_unitario=Decimal("150.00"),
                observaciones="Sin sal & <x>",
            )
        ],
    )


def _build_history(
    zona: str = "America/Argentina/Buenos_Aires",
) -> ProviderHistoryView:
    base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    return ProviderHistoryView(
        cliente_id=31,
        comercio_id=1,
        entries=[
            ProviderHistoryEntry(
                receipt=ProviderReceiptView(
                    id=10,
                    fecha_recepcion=base,
                    fecha_recepcion_local=format_local_datetime(base, zona),
                    proveedor="twilio",
                    canal_id=5,
                ),
                outbounds=[
                    OutboundMessageView(
                        id=20,
                        sequence=0,
                        fecha_creacion=base,
                        fecha_creacion_local=format_local_datetime(base, zona),
                        cuerpo="Hola <b>visitante</b>",
                        estado="delivered",
                        intentos=1,
                        estado_proveedor="delivered",
                        estado_proveedor_en=base,
                        estado_proveedor_en_local=format_local_datetime(base, zona),
                        categoria_ultimo_fallo=None,
                        codigo_ultimo_fallo=None,
                    )
                ],
            )
        ],
    )


class PanelAuthTest(unittest.TestCase):
    """The panel surface uses HTTP Basic; the configured admin token
    is the password and the username is ignored."""

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

    def test_missing_credential_returns_401_with_www_authenticate(self) -> None:
        response = self.client.get("/admin/pilot/orders")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )
        self.assertEqual(
            response.headers.get("www-authenticate"), "Basic"
        )
        self.session_override.assert_not_called()

    def test_wrong_password_returns_401(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders",
            headers=_basic_auth_header("any", "definitely-wrong"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )
        self.session_override.assert_not_called()

    def test_correct_password_with_ignored_username_succeeds(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored-user", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_empty_username_with_correct_password_succeeds(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)


class PanelAuthMisconfiguredTest(unittest.TestCase):
    """The panel surface mirrors the JSON API when the configured
    administrative token is absent: it returns ``503`` and never
    invokes a business service or a database session."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings(token=None)
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_missing_config_returns_503(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders",
            headers=_basic_auth_header("any", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential authentication is unavailable"},
        )
        self.session_override.assert_not_called()

    def test_blank_config_returns_503(self) -> None:
        with patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings(token="   "),
        ):
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("any", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 503)


class PanelExistingJsonApiUnchangedTest(unittest.TestCase):
    """The panel only protects its own routes; every other JSON API
    keeps requiring ``X-Admin-Token`` and never accepts HTTP Basic."""

    def setUp(self) -> None:
        self.app = backend_main_app = _import_main_app()
        self.client = TestClient(backend_main_app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()

    def test_comercios_get_still_requires_x_admin_token(self) -> None:
        response = self.client.get(
            "/comercios/1",
            headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )

    def test_x_admin_token_header_still_works_for_comercios(self) -> None:
        with patch.object(
            _routers_comercios(),
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
            )
            response = self.client.get(
                "/comercios/1",
                headers={_admin_token_header(): CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        service.get_by_id.assert_called_once_with(1)


def _import_main_app():
    import backend.main as main_module
    return main_module.app


def _admin_token_header() -> str:
    return dependencies_module.ADMIN_TOKEN_HEADER


def _routers_comercios():
    import backend.routers.comercios as comercios_module
    return comercios_module


class PanelListRouteTest(unittest.TestCase):
    """The list view honours the documented pagination bounds and
    applies the validated filters without mutating state."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_list_renders_default_filters(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Listado de pedidos", response.text)

    def test_list_with_invalid_page_size_returns_400(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_instance = MagicMock(name="ServiceInstance")
            service_cls.return_value = service_instance
            response = self.client.get(
                "/admin/pilot/orders?page_size=75",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("page_size must be 25, 50 or 100", response.text)
        service_instance.list_orders.assert_not_called()
        service_instance.get_detail.assert_not_called()
        service_instance.get_provider_history.assert_not_called()

    def test_list_with_invalid_date_returns_400(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_instance = MagicMock(name="ServiceInstance")
            service_cls.return_value = service_instance
            response = self.client.get(
                "/admin/pilot/orders?from=not-a-date",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ISO date", response.text)
        service_instance.list_orders.assert_not_called()

    def test_list_with_oversized_range_returns_400(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_instance = MagicMock(name="ServiceInstance")
            service_cls.return_value = service_instance
            response = self.client.get(
                "/admin/pilot/orders?from=2026-06-01&to=2026-08-15",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("31 days", response.text)
        service_instance.list_orders.assert_not_called()

    def test_list_with_inverted_range_returns_400(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_instance = MagicMock(name="ServiceInstance")
            service_cls.return_value = service_instance
            response = self.client.get(
                "/admin/pilot/orders?from=2026-08-15&to=2026-08-01",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 400)
        service_instance.list_orders.assert_not_called()

    def test_list_renders_rows(self) -> None:
        alta = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        ultima = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
        inicio = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        ultimo_mov = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
        zona = "America/Argentina/Buenos_Aires"
        row = OrderListRow(
            pedido=OrderSummary(
                id=11,
                estado_pedido=EstadoPedido.INGRESADO,
                fecha_alta=alta,
                fecha_alta_local=format_local_datetime(alta, zona),
                fecha_ultima_modificacion=ultima,
                fecha_ultima_modificacion_local=format_local_datetime(ultima, zona),
            ),
            session=SessionSummary(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=inicio,
                datetime_inicio_local=format_local_datetime(inicio, zona),
                datetime_ultimo_movimiento=ultimo_mov,
                datetime_ultimo_movimiento_local=format_local_datetime(ultimo_mov, zona),
            ),
            commerce=CommerceSummary(
                id=1,
                nombre_fantasia="Comercio A",
                nombre_corto="A",
                zona_horaria=zona,
            ),
            client=ClientSummary(
                id=31,
                nombre="Ana",
                whatsapp="+5491100000001",
                activo=True,
            ),
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[row],
                    total=1,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("#11", response.text)
        self.assertIn("Comercio A", response.text)
        self.assertIn("Ana", response.text)
        self.assertIn("+5491100000001", response.text)


class PanelDetailRouteTest(unittest.TestCase):
    """The detail view loads only the requested pedido, never
    substitutes another pedido, and escapes every value."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_detail_renders_requested_pedido(self) -> None:
        detail = _build_detail()
        history = _build_history()
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail,
                history=history,
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Pedido #42", body)
        self.assertIn("Ana &amp; &lt;script&gt;", body)
        self.assertIn("Calle 123 &amp; &lt;b&gt;", body)
        self.assertIn("Llamar &amp; &lt;i&gt;", body)
        self.assertIn("Hola &lt;b&gt;visitante&lt;/b&gt;", body)
        self.assertIn("Efectivo", body)
        self.assertIn("Retiro", body)
        self.assertIn("twilio", body)

    def test_detail_does_not_show_provider_identifier_or_lease(self) -> None:
        detail = _build_detail()
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        zona = "America/Argentina/Buenos_Aires"
        history = ProviderHistoryView(
            cliente_id=31,
            comercio_id=1,
            entries=[
                ProviderHistoryEntry(
                    receipt=ProviderReceiptView(
                        id=10,
                        fecha_recepcion=base,
                        fecha_recepcion_local=format_local_datetime(base, zona),
                        proveedor="twilio",
                        canal_id=5,
                    ),
                    outbounds=[
                        OutboundMessageView(
                            id=20,
                            sequence=0,
                            fecha_creacion=base,
                            fecha_creacion_local=format_local_datetime(base, zona),
                            cuerpo="Hola!",
                            estado="delivered",
                            intentos=1,
                            estado_proveedor="delivered",
                            estado_proveedor_en=base,
                            estado_proveedor_en_local=format_local_datetime(base, zona),
                            categoria_ultimo_fallo=None,
                            codigo_ultimo_fallo=None,
                        )
                    ],
                )
            ],
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail, history=history
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertNotIn("SM-redacted", body)
        self.assertNotIn("SMxxxx", body)
        self.assertNotIn("lease-secret", body)

    def test_detail_invalid_pedido_returns_404(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders/abc",
            headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("abc", response.text)

    def test_detail_zero_pedido_returns_404(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders/0",
            headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 404)

    def test_detail_missing_pedido_returns_404(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(detail=None, history=None)
            response = self.client.get(
                "/admin/pilot/orders/9999",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)

    def test_detail_does_not_fall_back_to_other_pedido(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service = _stub_service(detail=None, history=None)
            service_cls.return_value = service
            response = self.client.get(
                "/admin/pilot/orders/9999",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
            self.client.get(
                "/admin/pilot/orders/7777",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(service.get_detail.call_count, 2)
        called_ids = [
            call.args[0] for call in service.get_detail.call_args_list
        ]
        self.assertEqual(called_ids, [9999, 7777])

    def test_detail_missing_payment_and_delivery_show_clear_absence(self) -> None:
        template = _build_detail()
        detail = OrderDetailView(
            pedido=template.pedido,
            session=template.session,
            client=template.client,
            commerce=template.commerce,
            direccion_entrega=template.direccion_entrega,
            observaciones=template.observaciones,
            datetime_entrega_programada=template.datetime_entrega_programada,
            datetime_entrega_programada_local=template.datetime_entrega_programada_local,
            medio_pago=None,
            metodo_entrega=None,
            lineas=template.lineas,
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail, history=_build_history()
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("sin medio de pago registrado", body)
        self.assertIn("sin método de entrega registrado", body)


class PanelNoMutationTest(unittest.TestCase):
    """The router must never call commit/rollback/flush/refresh/begin
    or close and must not expose any mutating form/button."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_list_does_not_mutate_session(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_detail_does_not_mutate_session(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_only_get_routes_are_registered(self) -> None:
        for route in router_module.router.routes:
            methods = getattr(route, "methods", set())
            self.assertTrue(
                methods.issubset({"GET", "HEAD"}),
                msg=f"non-GET methods registered: {methods}",
            )

    def test_templates_contain_no_mutating_form(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            list_response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertNotIn('method="post"', list_response.text)
        self.assertNotIn('method="POST"', list_response.text)
        self.assertNotIn('method="put"', list_response.text)
        self.assertNotIn('method="delete"', list_response.text)
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            detail_response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertNotIn("<form", detail_response.text)
        self.assertNotIn('method="post"', detail_response.text)


class PanelTemplatesEscapeTest(unittest.TestCase):
    """Templates auto-escape values; the rendered HTML never leaks a
    raw angle bracket or ampersand from user-controlled data."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        )
        self._settings_patcher.start()

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_detail_template_autoescapes(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertNotIn("Ana & <script>", body)
        self.assertNotIn("Comercio & 'A'", body)
        self.assertNotIn("Calle 123 & <b>", body)
        self.assertNotIn("Llamar & <i>", body)
        self.assertNotIn("Hola <b>visitante</b>", body)

    def test_jinja_environment_is_autoescape_on(self) -> None:
        env = router_module._templates.env
        self.assertTrue(
            env.autoescape,
            msg="Jinja2 environment MUST enable autoescape for the panel",
        )


class PanelTimezoneRenderingTest(unittest.TestCase):
    """The HTML output of the list and detail templates renders the
    comercio's timezone next to every timestamp and labels the
    filter window as UTC. The instant itself is preserved in the
    view model."""

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

    def test_list_template_declares_filters_in_utc(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[],
                    total=0,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("UTC", body)
        self.assertIn("from", body)
        self.assertIn("to", body)

    def test_list_renders_per_row_zone_label(self) -> None:
        alta = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        row_ba = OrderListRow(
            pedido=OrderSummary(
                id=1,
                estado_pedido=EstadoPedido.INGRESADO,
                fecha_alta=alta,
                fecha_alta_local=format_local_datetime(
                    alta, "America/Argentina/Buenos_Aires"
                ),
                fecha_ultima_modificacion=alta,
                fecha_ultima_modificacion_local=format_local_datetime(
                    alta, "America/Argentina/Buenos_Aires"
                ),
            ),
            session=SessionSummary(
                id=10,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=alta,
                datetime_inicio_local=format_local_datetime(
                    alta, "America/Argentina/Buenos_Aires"
                ),
                datetime_ultimo_movimiento=alta,
                datetime_ultimo_movimiento_local=format_local_datetime(
                    alta, "America/Argentina/Buenos_Aires"
                ),
            ),
            commerce=CommerceSummary(
                id=1,
                nombre_fantasia="Comercio BA",
                nombre_corto="BA",
                zona_horaria="America/Argentina/Buenos_Aires",
            ),
            client=ClientSummary(
                id=31,
                nombre="Ana",
                whatsapp="+5491100000001",
                activo=True,
            ),
        )
        row_ny = OrderListRow(
            pedido=OrderSummary(
                id=2,
                estado_pedido=EstadoPedido.INGRESADO,
                fecha_alta=alta,
                fecha_alta_local=format_local_datetime(alta, "America/New_York"),
                fecha_ultima_modificacion=alta,
                fecha_ultima_modificacion_local=format_local_datetime(
                    alta, "America/New_York"
                ),
            ),
            session=SessionSummary(
                id=11,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=alta,
                datetime_inicio_local=format_local_datetime(alta, "America/New_York"),
                datetime_ultimo_movimiento=alta,
                datetime_ultimo_movimiento_local=format_local_datetime(
                    alta, "America/New_York"
                ),
            ),
            commerce=CommerceSummary(
                id=2,
                nombre_fantasia="Comercio NY",
                nombre_corto="NY",
                zona_horaria="America/New_York",
            ),
            client=ClientSummary(
                id=32,
                nombre="Bob",
                whatsapp="+15551234567",
                activo=True,
            ),
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(
                    rows=[row_ba, row_ny],
                    total=2,
                    page=1,
                    page_size=25,
                )
            )
            response = self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("America/Argentina/Buenos_Aires", body)
        self.assertIn("America/New_York", body)
        self.assertIn("2026-08-12T06:00:00-03:00", body)
        self.assertIn("2026-08-12T05:00:00-04:00", body)

    def test_detail_renders_zone_label_for_each_timestamp(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("America/Argentina/Buenos_Aires", body)
        self.assertIn("2026-08-12T06:00:00-03:00", body)

    def test_detail_renders_fallback_utc_label_for_invalid_zone(self) -> None:
        from dataclasses import replace

        template = _build_detail()
        invalid_zone = "Not/A_Real_Zone"
        detail = OrderDetailView(
            pedido=replace(
                template.pedido,
                fecha_alta_local=format_local_datetime(
                    template.pedido.fecha_alta, invalid_zone
                ),
                fecha_ultima_modificacion_local=format_local_datetime(
                    template.pedido.fecha_ultima_modificacion, invalid_zone
                ),
            ),
            session=replace(
                template.session,
                datetime_inicio_local=format_local_datetime(
                    template.session.datetime_inicio, invalid_zone
                ),
                datetime_ultimo_movimiento_local=format_local_datetime(
                    template.session.datetime_ultimo_movimiento, invalid_zone
                ),
            ),
            client=template.client,
            commerce=replace(template.commerce, zona_horaria=invalid_zone),
            direccion_entrega=template.direccion_entrega,
            observaciones=template.observaciones,
            datetime_entrega_programada=template.datetime_entrega_programada,
            datetime_entrega_programada_local=template.datetime_entrega_programada_local,
            medio_pago=template.medio_pago,
            metodo_entrega=template.metodo_entrega,
            lineas=template.lineas,
        )
        history = _build_history(zona=invalid_zone)
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail, history=history
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("Not/A_Real_Zone", body)
        self.assertIn("2026-08-12T09:00:00+00:00", body)

    def test_router_passes_zona_horaria_to_history_query(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_instance = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            service_cls.return_value = service_instance
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        service_instance.get_provider_history.assert_called_once()
        kwargs = service_instance.get_provider_history.call_args.kwargs
        self.assertEqual(
            kwargs.get("zona_horaria"), "America/Argentina/Buenos_Aires"
        )


class PanelTimezoneRegressionTest(unittest.TestCase):
    """Regression coverage: the panel still uses HTTP Basic, escapes
    every rendered value and never mutates a database session after
    the timezone enhancement."""

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

    def test_basic_auth_is_still_required_for_timezone_rendering(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(rows=[], total=0, page=1, page_size=25)
            )
            response = self.client.get("/admin/pilot/orders")
        self.assertEqual(response.status_code, 401)

    def test_zone_label_is_escaped(self) -> None:
        from dataclasses import replace

        evil_zone = "Not/A_Real_Zone"
        template = _build_detail()
        detail = OrderDetailView(
            pedido=replace(
                template.pedido,
                fecha_alta_local=format_local_datetime(
                    template.pedido.fecha_alta, evil_zone
                ),
                fecha_ultima_modificacion_local=format_local_datetime(
                    template.pedido.fecha_ultima_modificacion, evil_zone
                ),
            ),
            session=replace(
                template.session,
                datetime_inicio_local=format_local_datetime(
                    template.session.datetime_inicio, evil_zone
                ),
                datetime_ultimo_movimiento_local=format_local_datetime(
                    template.session.datetime_ultimo_movimiento, evil_zone
                ),
            ),
            client=template.client,
            commerce=replace(template.commerce, zona_horaria=evil_zone),
            direccion_entrega=template.direccion_entrega,
            observaciones=template.observaciones,
            datetime_entrega_programada=template.datetime_entrega_programada,
            datetime_entrega_programada_local=template.datetime_entrega_programada_local,
            medio_pago=template.medio_pago,
            metodo_entrega=template.metodo_entrega,
            lineas=template.lineas,
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail,
                history=_build_history(zona=evil_zone),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("UTC", body)
        self.assertIn(evil_zone, body)

    def test_commerce_zona_horaria_with_html_is_escaped(self) -> None:
        from dataclasses import replace

        evil_raw = '"><img src=x onerror=alert(1)>'
        template = _build_detail()
        detail = OrderDetailView(
            pedido=template.pedido,
            session=template.session,
            client=template.client,
            commerce=replace(template.commerce, zona_horaria=evil_raw),
            direccion_entrega=template.direccion_entrega,
            observaciones=template.observaciones,
            datetime_entrega_programada=template.datetime_entrega_programada,
            datetime_entrega_programada_local=template.datetime_entrega_programada_local,
            medio_pago=template.medio_pago,
            metodo_entrega=template.metodo_entrega,
            lineas=template.lineas,
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail,
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertNotIn("<img src=x onerror=alert(1)>", body)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", body)

    def test_no_session_mutation_after_timezone_render(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                list_view=OrderListView(rows=[], total=0, page=1, page_size=25)
            )
            self.client.get(
                "/admin/pilot/orders",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
