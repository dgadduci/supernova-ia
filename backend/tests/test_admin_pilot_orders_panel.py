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
    PendingContextDebugView,
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

    def test_only_get_routes_are_registered_outside_local_test(self) -> None:
        """The panel now owns one POST route — the panel-local test
        channel for the exact selected Pedido. Every other route
        must remain GET-only."""
        for route in router_module.router.routes:
            methods = getattr(route, "methods", set())
            if getattr(route, "path", "").endswith("/local-test"):
                self.assertEqual(
                    methods,
                    {"POST"},
                    msg=(
                        f"local-test route must be POST only, got {methods}"
                    ),
                )
                continue
            self.assertTrue(
                methods.issubset({"GET", "HEAD"}),
                msg=f"non-GET methods registered: {methods}",
            )

    def test_templates_contain_no_mutating_form_outside_local_test(self) -> None:
        """The list view carries only the documented GET filter
        form; the detail view carries exactly the documented
        local-test form pointing at the panel-local POST route,
        never at any external action."""
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
        self.assertIn('method="get"', list_response.text)
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
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotIn('method="put"', detail_response.text)
        self.assertNotIn('method="delete"', detail_response.text)
        self.assertIn('action="/admin/pilot/orders/42/local-test"', detail_response.text)
        self.assertIn('X-Local-Test-Origin', detail_response.text)


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


def _build_detail_with_pending_debug(
    *,
    pending_debug: PendingContextDebugView | None,
) -> OrderDetailView:
    base = _build_detail()
    return OrderDetailView(
        pedido=base.pedido,
        session=base.session,
        client=base.client,
        commerce=base.commerce,
        direccion_entrega=base.direccion_entrega,
        observaciones=base.observaciones,
        datetime_entrega_programada=base.datetime_entrega_programada,
        datetime_entrega_programada_local=base.datetime_entrega_programada_local,
        medio_pago=base.medio_pago,
        metodo_entrega=base.metodo_entrega,
        lineas=base.lineas,
        pending_debug=pending_debug,
    )


def _strip_css(html: str) -> str:
    """Remove the inline ``<style>`` block so the tests can inspect
    the rendered DOM without the static CSS colour hex codes
    polluting the search."""
    start = html.find("<style>")
    end = html.find("</style>")
    if start == -1 or end == -1:
        return html
    return html[:start] + html[end + len("</style>"):]


class PanelDebugConsoleRenderingTest(unittest.TestCase):
    """The detail view renders the 30/30/40 three-column console
    with the local-test chat, the existing detail/history and the
    safe execution-state column. Every privacy-bounded value is
    emitted as text; no payload, raw JSON, source text, candidate
    identifier, environment variable, configuration value or
    secret ever appears in the rendered HTML."""

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

    def test_detail_renders_three_columns(self) -> None:
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=2,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=0,
            schema_version=1,
            consistency="consistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn('class="debug-grid"', body)
        self.assertIn('class="debug-column debug-chat"', body)
        self.assertIn('class="debug-column debug-detail"', body)
        self.assertIn('class="debug-column debug-state"', body)
        # CSS grid columns
        self.assertIn(
            "minmax(16rem, 30%) minmax(16rem, 30%) minmax(20rem, 40%)",
            body,
        )
        # Narrow viewport stacking
        self.assertIn("@media (max-width: 900px)", body)

    def test_detail_renders_warning_label(self) -> None:
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
        self.assertIn(
            "Canal local; no envía a WhatsApp/Twilio",
            body,
        )
        self.assertNotIn(
            "Canal de prueba local — no WhatsApp / no Twilio",
            body,
        )
        self.assertNotIn("Lo único durable", body)

    def test_detail_renders_pending_debug_for_valid_state(self) -> None:
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=3,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=2,
            schema_version=1,
            consistency="consistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("product_selection", body)
        self.assertIn("valid", body)
        self.assertIn("agregar_producto", body)
        self.assertIn("pending_resolution", body)
        self.assertIn("3", body)
        self.assertIn("1", body)

    def test_detail_renders_invalid_state_with_no_payload(self) -> None:
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="invalid",
            active_intent="none",
            active_status="none",
            candidate_count=0,
            requirements_pending_count=0,
            requirements_completed_count=0,
            queue_length=0,
            schema_version=None,
            consistency="inconsistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertIn("invalid", body)
        self.assertIn("inconsistent", body)
        # Payload/candidate IDs/secret-like values must NEVER appear.
        for forbidden in (
            "SECRET-SOURCE",
            "SECRET-VALUE",
            "candidate_ids",
            "resolved_data",
            "source_text",
            "pending_intents",
            "raw_context_type",
            "diagnostics",
            "secret",
            "OPENAI",
            "API_KEY",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)

    def test_detail_renders_none_state_when_no_pending_debug(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=None),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sin estado de pending", response.text)

    def test_transcript_uses_textContent_only(self) -> None:
        """The browser transcript must never use ``innerHTML`` or
        ``outerHTML`` to insert operator input or mapped responses.
        Only ``textContent`` is allowed for the volatile transcript
        so HTML-like input is rendered as literal text."""
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
        body_no_css = _strip_css(response.text)
        # The transcript uses textContent only.
        self.assertIn("textContent", body_no_css)
        self.assertNotIn("innerHTML", body_no_css)
        self.assertNotIn("outerHTML", body_no_css)

    def test_transcript_never_uses_storage_or_url(self) -> None:
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
        body_no_css = _strip_css(response.text)
        for forbidden in (
            "localStorage",
            "sessionStorage",
            "document.cookie",
            "history.pushState",
            "history.replaceState",
            "URLSearchParams",
            "window.location.search",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body_no_css)

    def test_detail_local_test_form_is_post_only(self) -> None:
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
        self.assertIn('action="/admin/pilot/orders/42/local-test"', body)
        self.assertIn('method="post"', body)
        self.assertIn("X-Local-Test-Origin", body)
        self.assertIn("maxlength=\"500\"", body)


class PanelFixedViewportRenderingTest(unittest.TestCase):
    """Task 7.1: the local-test transcript has a single fixed
    responsive viewport height that does not grow with content."""

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

    def test_transcript_uses_fixed_height_not_min_max_range(self) -> None:
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
        css = response.text
        # The fixed viewport must use one stable height token so the
        # column cannot grow with additional turns.
        self.assertIn("height: 12rem", css)
        # The transcript must NOT use a min/max range that could
        # expand with content.
        self.assertNotIn("min-height: 8rem", css)
        self.assertNotIn("max-height: 24rem;", css)
        # The transcript must keep its own scroll context.
        self.assertIn("overflow-y: auto", css)
        # Wrapping is preserved for long operator/customer text.
        self.assertIn("white-space: pre-wrap", css)
        self.assertIn("word-break: break-word", css)

    def test_grid_uses_responsive_columns_and_align_start(self) -> None:
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
        css = response.text
        self.assertIn(
            "minmax(16rem, 30%) minmax(16rem, 30%) minmax(20rem, 40%)",
            css,
        )
        self.assertIn("align-items: start", css)
        # Narrow viewport stacking is preserved.
        self.assertIn("@media (max-width: 900px)", css)


class PanelExecutionStateResponseTest(unittest.TestCase):
    """Task 7.2: a successful local-test run returns a typed closed
    ``execution_state`` snapshot alongside the mapped responses. The
    snapshot mirrors the documented closed fields of
    :class:`PendingContextDebugView` and never serializes raw
    payloads, sessions, pedidos or pending JSON."""

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

    def _post(self):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=headers,
        )

    def _build_session(self, *, context_type, pending_intents):
        session = MagicMock(name="ExactSession")
        session.id = 21
        session.id_pedido = 42
        session.id_comercio = 1
        session.id_cliente = 31
        session.estado_session = "activa"
        session.context_type = context_type
        session.pending_intents = pending_intents
        return session

    def test_response_contains_closed_execution_state_for_valid_session(
        self,
    ) -> None:
        exact_session = self._build_session(
            context_type="product_selection",
            pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "quiero una pizza",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "candidate_ids": [1, 2, 3],
                    "requirements": [
                        {"name": "size", "status": "pending"},
                        {"name": "qty", "status": "completed"},
                    ],
                },
                "queue": [],
            },
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ) as loader, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ) as snapshot_loader, patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="Hola",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(snapshot_loader.call_count, 1)
        body = response.json()
        self.assertIn("execution_state", body)
        state = body["execution_state"]
        self.assertEqual(
            set(state.keys()),
            {
                "context_type",
                "pending_encoding",
                "active_intent",
                "active_status",
                "candidate_count",
                "requirements_pending_count",
                "requirements_completed_count",
                "queue_length",
                "schema_version",
                "consistency",
            },
        )
        self.assertEqual(state["context_type"], "product_selection")
        self.assertEqual(state["pending_encoding"], "valid")
        self.assertEqual(state["active_intent"], "agregar_producto")
        self.assertEqual(state["active_status"], "pending_resolution")
        self.assertEqual(state["candidate_count"], 3)
        self.assertEqual(state["requirements_pending_count"], 1)
        self.assertEqual(state["requirements_completed_count"], 1)
        self.assertEqual(state["queue_length"], 0)
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["consistency"], "consistent")

    def test_response_does_not_serialize_session_or_pedido(self) -> None:
        exact_session = self._build_session(
            context_type="product_selection",
            pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "SECRET-SOURCE",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "candidate_ids": [101, 202],
                    "resolved_data": {"secret": "SECRET-VALUE"},
                },
                "queue": [
                    {
                        "intent": "agregar_producto",
                        "source_text": "q1",
                        "status": "executed",
                        "handler": "agregar_producto",
                    },
                ],
            },
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        body_text = response.text
        self.assertEqual(response.status_code, 200)
        for forbidden in (
            "SECRET-SOURCE",
            "SECRET-VALUE",
            "candidate_ids",
            "resolved_data",
            "source_text",
            "pending_intents",
            "id_pedido",
            "id_comercio",
            "id_cliente",
            "OPENAI",
            "API_KEY",
            "identificador_proveedor",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body_text)

    def test_response_handles_empty_session_state(self) -> None:
        exact_session = self._build_session(
            context_type=None,
            pending_intents=None,
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        state = response.json()["execution_state"]
        self.assertEqual(state["context_type"], "none")
        self.assertEqual(state["pending_encoding"], "empty")
        self.assertEqual(state["active_intent"], "none")
        self.assertEqual(state["active_status"], "none")
        self.assertEqual(state["candidate_count"], 0)
        self.assertEqual(state["requirements_pending_count"], 0)
        self.assertEqual(state["requirements_completed_count"], 0)
        self.assertEqual(state["queue_length"], 0)
        self.assertIsNone(state["schema_version"])
        self.assertEqual(state["consistency"], "none")

    def test_response_handles_malformed_pending_state(self) -> None:
        exact_session = self._build_session(
            context_type="product_selection",
            pending_intents={"active": "not-a-dict"},
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        state = response.json()["execution_state"]
        self.assertEqual(state["pending_encoding"], "invalid")
        self.assertEqual(state["consistency"], "inconsistent")
        self.assertIsNone(state["schema_version"])

    def test_route_does_not_call_commit_rollback_flush_refresh_begin_close_expire(
        self,
    ) -> None:
        exact_session = self._build_session(
            context_type=None,
            pending_intents=None,
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.expire.assert_not_called()

    def test_successful_turn_with_pedido_now_ingresado_still_returns_snapshot(
        self,
    ) -> None:
        """A legitimate confirm-order turn may flip the exact pedido
        from ``borrador`` to ``ingresado``. The post-turn snapshot
        MUST still be returned, the mapped responses MUST be
        preserved, and the route MUST NOT search for a successor
        session or another active session for the same
        cliente/comercio.

        We simulate this by having the post-turn snapshot loader see
        the exact same pedido/session identity (the processor's
        commit did not delete or re-point the row) — only the
        ``estado_pedido`` change matters, and that change is
        invisible to the snapshot loader because it deliberately
        does not check ``borrador``.
        """
        exact_session = self._build_session(
            context_type="delivery_window",
            pending_intents={
                "version": 1,
                "active": None,
                "queue": [],
            },
        )
        exact_pedido = MagicMock(name="ExactPedido")
        exact_pedido.estado_pedido = EstadoPedido.INGRESADO
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ) as loader, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ) as snapshot_loader, patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="Pedido confirmado",
                    intent="confirmar_pedido",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        # Pre-turn loader is invoked once; the post-turn snapshot
        # loader is invoked exactly once with the exact identity.
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(snapshot_loader.call_count, 1)
        # The post-turn loader received the exact pedido_id and
        # session_id; it never received a fallback parameter.
        snapshot_args = snapshot_loader.call_args.args
        self.assertEqual(snapshot_args[1], 42)
        self.assertEqual(snapshot_args[2], exact_session.id)
        body = response.json()
        # Mapped responses are preserved.
        self.assertEqual(
            body["responses"],
            [
                {
                    "message": "Pedido confirmado",
                    "intent": "confirmar_pedido",
                    "status": "executed",
                }
            ],
        )
        # Closed execution_state is present and has only the
        # documented keys.
        self.assertIn("execution_state", body)
        self.assertEqual(
            set(body["execution_state"].keys()),
            {
                "context_type",
                "pending_encoding",
                "active_intent",
                "active_status",
                "candidate_count",
                "requirements_pending_count",
                "requirements_completed_count",
                "queue_length",
                "schema_version",
                "consistency",
            },
        )
        # No transaction control from the router side.
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.expire.assert_not_called()
        # The processor was called exactly once for the exact
        # selected session.
        process_mock.assert_called_once()
        self.assertIs(process_mock.call_args.args[1], exact_session)

    def test_snapshot_loader_rejects_only_when_exact_identity_is_gone(
        self,
    ) -> None:
        """The post-turn snapshot loader returns ``None`` ONLY when
        the exact session/pedido identity is gone (e.g., session
        deleted or re-pointed to a different pedido during the
        turn). In that case the route returns the documented
        generic rejection and never fabricates a snapshot.

        Crucially, the loader does NOT consider ``borrador``
        eligibility — so a pedido that is now ``ingresado`` but
        still references the same session id is NOT a rejection.
        """
        exact_session = self._build_session(
            context_type=None,
            pending_intents=None,
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=None,
        ) as snapshot_loader, patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(snapshot_loader.call_count, 1)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        self.assertNotIn("execution_state", body)

    def test_route_rejects_unexpected_response_fields(self) -> None:
        """The wire payload is enforced explicitly via the
        ``LocalTestResponse`` schema, so unexpected fields cannot
        leak into the response even through a regression."""
        exact_session = self._build_session(
            context_type=None,
            pending_intents=None,
        )
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {"responses", "execution_state"},
        )


class PanelExecutionStateSerializationTest(unittest.TestCase):
    """The :func:`_serialize_execution_state` helper projects only the
    documented closed fields and refuses to emit other members."""

    def test_serialize_emits_only_documented_fields(self) -> None:
        from backend.routers.admin_pilot_orders import (
            _serialize_execution_state,
        )
        from backend.services.pilot_order_operations_view_service import (
            PendingContextDebugView,
        )

        view = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=2,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=3,
            schema_version=1,
            consistency="consistent",
        )
        serialized = _serialize_execution_state(view)
        self.assertEqual(
            set(serialized.model_dump().keys()),
            {
                "context_type",
                "pending_encoding",
                "active_intent",
                "active_status",
                "candidate_count",
                "requirements_pending_count",
                "requirements_completed_count",
                "queue_length",
                "schema_version",
                "consistency",
            },
        )

    def test_serialize_handles_none_schema_version(self) -> None:
        from backend.routers.admin_pilot_orders import (
            _serialize_execution_state,
        )
        from backend.services.pilot_order_operations_view_service import (
            PendingContextDebugView,
        )

        view = PendingContextDebugView(
            context_type="none",
            pending_encoding="empty",
            active_intent="none",
            active_status="none",
            candidate_count=0,
            requirements_pending_count=0,
            requirements_completed_count=0,
            queue_length=0,
            schema_version=None,
            consistency="none",
        )
        serialized = _serialize_execution_state(view)
        self.assertIsNone(serialized.schema_version)


class PanelExecutionStateDetailCellsTest(unittest.TestCase):
    """The detail template renders every execution-state cell with a
    ``data-debug-*`` attribute so the browser-side handler can update
    it with ``textContent`` after a successful turn."""

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

    def test_every_state_cell_has_data_debug_attribute(self) -> None:
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=2,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=0,
            schema_version=1,
            consistency="consistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        for attr in (
            "data-debug-context",
            "data-debug-encoding",
            "data-debug-active-intent",
            "data-debug-active-status",
            "data-debug-candidate-count",
            "data-debug-requirements-pending",
            "data-debug-requirements-completed",
            "data-debug-queue-length",
            "data-debug-schema-version",
            "data-debug-consistency",
        ):
            with self.subTest(attr=attr):
                self.assertIn(attr, body)

    def test_browser_handler_updates_state_cells_with_textContent(self) -> None:
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
        body_no_css = _strip_css(response.text)
        # The state-refresh handler must use textContent for every
        # cell and never build HTML.
        self.assertIn("textContent", body_no_css)
        self.assertNotIn("innerHTML", body_no_css)
        self.assertNotIn("outerHTML", body_no_css)
        # It must look up every documented cell by its data attribute.
        for attr in (
            "data-debug-context",
            "data-debug-encoding",
            "data-debug-active-intent",
            "data-debug-active-status",
            "data-debug-candidate-count",
            "data-debug-requirements-pending",
            "data-debug-requirements-completed",
            "data-debug-queue-length",
            "data-debug-schema-version",
            "data-debug-consistency",
        ):
            with self.subTest(attr=attr):
                self.assertIn(attr, body_no_css)

    def test_browser_handler_skips_state_update_on_failure(self) -> None:
        """The handler must never synthesize a snapshot when the
        response is not successful, the JSON is malformed or the
        network call fails. The error branch must only append an
        error line and update the status text."""
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
        body_no_css = _strip_css(response.text)
        # The handler must check both ``ok`` and ``execution_state`` so
        # the snapshot is only applied on a successful payload.
        self.assertIn("execution_state", body_no_css)
        self.assertIn("updateExecutionState", body_no_css)
        self.assertIn("Error del canal local", body_no_css)


class PanelCompactStateLayoutTest(unittest.TestCase):
    """Task 8.2: the execution-state column renders each label and
    its value as a compact ``nombre: valor`` pair while preserving
    every existing ``data-debug-*`` value selector."""

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

    def test_state_rows_pair_label_and_value(self) -> None:
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=2,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=0,
            schema_version=1,
            consistency="consistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        # The execution-state markup must wrap each label/value in
        # a row container so the operator sees ``nombre: valor``
        # together on one logical row.
        self.assertIn("debug-state-row", body)
        # Each documented label is emitted with its colon suffix so
        # the visual pair is explicit.
        for label in (
            "Contexto:",
            "Pending:",
            "Intent activo:",
            "Status activo:",
            "Candidatos:",
            "Requirements pendientes:",
            "Requirements completados:",
            "Cola:",
            "Versión del pending:",
            "Consistencia:",
        ):
            with self.subTest(label=label):
                self.assertIn(label, body)

    def test_state_rows_preserve_data_debug_selectors(self) -> None:
        """The compact rendering keeps every existing
        ``data-debug-*`` value selector so the local-test refresh
        JavaScript continues to find the cells it has to update."""
        pending = PendingContextDebugView(
            context_type="product_selection",
            pending_encoding="valid",
            active_intent="agregar_producto",
            active_status="pending_resolution",
            candidate_count=2,
            requirements_pending_count=1,
            requirements_completed_count=1,
            queue_length=0,
            schema_version=1,
            consistency="consistent",
        )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail_with_pending_debug(pending_debug=pending),
                history=_build_history(),
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        body = response.text
        for attr in (
            "data-debug-context",
            "data-debug-encoding",
            "data-debug-active-intent",
            "data-debug-active-status",
            "data-debug-candidate-count",
            "data-debug-requirements-pending",
            "data-debug-requirements-completed",
            "data-debug-queue-length",
            "data-debug-schema-version",
            "data-debug-consistency",
        ):
            with self.subTest(attr=attr):
                self.assertIn(attr, body)

    def test_state_rows_use_flex_layout_in_css(self) -> None:
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
        css = response.text
        # The compact rows rely on flex layout so the label and the
        # value stay on the same baseline even with long counts.
        self.assertIn("debug-state-row", css)
        self.assertIn("display: flex", css)


class PanelCompactChatLayoutTest(unittest.TestCase):
    """Task 8.2: the transcript shrinks to a single 12rem scroll
    viewport, the long warning is removed and a short local-only
    note sits below the transcript."""

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

    def test_transcript_height_is_12rem_not_24rem(self) -> None:
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
        css = response.text
        # Task 8.2 shrinks the fixed transcript viewport from 24rem
        # to 12rem. The new value must be present, the old one must
        # not.
        self.assertIn("height: 12rem", css)
        self.assertNotIn("height: 24rem", css)

    def test_long_warning_is_absent_and_short_note_is_present(self) -> None:
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
        # The verbose warning is removed entirely.
        self.assertNotIn(
            "Canal de prueba local — no WhatsApp / no Twilio",
            body,
        )
        self.assertNotIn("Lo único durable", body)
        # The short note sits below the transcript/status.
        self.assertIn(
            "Canal local; no envía a WhatsApp/Twilio",
            body,
        )
        # It must be visually marked as a separate note so the
        # operator can still recognise the local-only intent.
        self.assertIn("debug-channel-note", body)


class PanelLinesScrollContainerTest(unittest.TestCase):
    """Task 8.2: the order-lines table lives inside a bounded
    scroll container so every line remains accessible without
    expanding the centre column."""

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

    def test_lines_table_is_inside_scroll_container(self) -> None:
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
        # The scroll container must wrap the existing table so
        # every line stays accessible without column expansion.
        self.assertIn("debug-lines-scroll", body)
        self.assertIn("<table>", body)
        self.assertIn("Pan &lt;b&gt;", body)

    def test_lines_scroll_container_css_is_bounded(self) -> None:
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
        css = response.text
        self.assertIn("debug-lines-scroll", css)
        self.assertIn("overflow: auto", css)
        self.assertIn("max-height", css)


class PanelLocalTestAuthExactTargetNoProviderRegressionTest(
    unittest.TestCase,
):
    """Task 7.3: the auth/exact-target/no-provider and transaction
    boundaries are preserved after the console-refresh amendment."""

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

    def test_router_source_still_excludes_provider_worker_twilio(self) -> None:
        from pathlib import Path

        forbidden = (
            "from backend.intents.handlers",
            "from backend.intents.context",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "from backend.llm",
            "from backend.services.session_service",
            "from backend.providers",
            "from backend.workers",
            "from backend.coordinators",
            "import requests",
            "import twilio",
            "MessagingResponse",
            "OutboundRow",
            "ProviderInboundMessageCoordinator",
            "ProviderReceipt",
        )
        source = Path(router_module.__file__).read_text(encoding="utf-8")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, source)

    def test_rejection_with_closed_session_does_not_simulate_snapshot(self) -> None:
        """A rejected submission or a non-success response must
        never produce an ``execution_state`` member. The browser
        keeps the prior snapshot in place."""
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ):
            headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
            headers["X-Local-Test-Origin"] = "same-origin"
            response = self.client.post(
                "/admin/pilot/orders/42/local-test",
                json={"message": "hola"},
                headers=headers,
            )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertNotIn("execution_state", body)

    def test_non_success_response_without_execution_state(self) -> None:
        """Sends a wrong origin header so the documented generic
        rejection fires. The body MUST NOT contain ``execution_state``."""
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        # No X-Local-Test-Origin header.
        response = self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertNotIn("execution_state", body)

    def test_response_does_not_emit_session_or_pedido_fields(self) -> None:
        """The successful response contract is enforced via the
        ``LocalTestResponse`` schema and never leaks the raw
        Session, Pedido or pending JSON under any key."""
        exact_session = MagicMock(name="ExactSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = "product_selection"
        exact_session.pending_intents = {
            "version": 1,
            "active": {
                "intent": "agregar_producto",
                "source_text": "SECRET-TEXT",
                "status": "pending_resolution",
                "handler": "agregar_producto",
                "candidate_ids": [101, 202],
            },
            "queue": [],
        }
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
            headers["X-Local-Test-Origin"] = "same-origin"
            response = self.client.post(
                "/admin/pilot/orders/42/local-test",
                json={"message": "hola"},
                headers=headers,
            )
        body = response.json()
        body_text = response.text
        self.assertEqual(response.status_code, 200)
        # The body must contain exactly the two documented keys.
        self.assertEqual(set(body.keys()), {"responses", "execution_state"})
        for forbidden in (
            "SECRET-TEXT",
            "candidate_ids",
            "source_text",
            "pending_intents",
            "id_pedido",
            "id_comercio",
            "id_cliente",
            "OPENAI",
            "API_KEY",
            "settings",
            "identificador_proveedor",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body_text)
        # The execution_state key must NOT leak the raw values either.
        self.assertEqual(
            set(body["execution_state"].keys()),
            {
                "context_type",
                "pending_encoding",
                "active_intent",
                "active_status",
                "candidate_count",
                "requirements_pending_count",
                "requirements_completed_count",
                "queue_length",
                "schema_version",
                "consistency",
            },
        )


class PanelLocalTestRouteAuthTest(unittest.TestCase):
    """The local-test POST route is mounted behind the same panel
    Basic authentication as the rest of the route family. Missing
    or wrong credentials return 401 with no business work."""

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

    def test_missing_credential_returns_401(self) -> None:
        response = self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers={"X-Local-Test-Origin": "same-origin"},
        )
        self.assertEqual(response.status_code, 401)
        self.session_override.assert_not_called()

    def test_wrong_password_returns_401(self) -> None:
        response = self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers={
                **_basic_auth_header("ignored", "definitely-wrong"),
                "X-Local-Test-Origin": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 401)


class PanelLocalTestRouteHeaderTest(unittest.TestCase):
    """The local-test POST route requires the documented same-origin
    custom header. Cross-origin form posts cannot set it, so the
    header acts as the CSRF defence."""

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

    def _post(self, *, origin_value):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        if origin_value is not None:
            headers["X-Local-Test-Origin"] = origin_value
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=headers,
        )

    def test_missing_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(origin_value=None)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        process_mock.assert_not_called()

    def test_wrong_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(origin_value="attacker.example")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()


class PanelLocalTestRouteBodyValidationTest(unittest.TestCase):
    """Body validation rejects empty, malformed and oversized
    payloads before the pipeline is invoked."""

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

    def _post(self, *, body, **kwargs):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            headers=headers,
            **kwargs,
        )

    def test_empty_body_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(body=None, json={})
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_non_string_message_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(body=None, json={"message": 123})
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_extra_field_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(
                body=None, json={"message": "hola", "extra": "x"}
            )
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_oversized_message_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(
                body=None,
                json={"message": "x" * 501},
            )
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_empty_string_message_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            response = self._post(body=None, json={"message": ""})
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()


class PanelLocalTestRouteRevalidationTest(unittest.TestCase):
    """The route re-validates the exact selected Pedido. Any
    mismatch (missing, closed, non-borrador, foreign session) must
    return the generic rejection without invoking the pipeline."""

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

    def _post(self, pedido_id: str = "42"):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            f"/admin/pilot/orders/{pedido_id}/local-test",
            json={"message": "hola"},
            headers=headers,
        )

    def _stub_loader_returning(self, return_value):
        return patch.object(
            router_module,
            "_load_local_test_session",
            return_value=return_value,
        )

    def test_invalid_pedido_id_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="abc")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_missing_pedido_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="9999")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_loader_rejection_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="42")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_loader_rejection_returns_generic_message(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="42")
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        # The rejection body must never echo back the reason.
        self.assertNotIn("invalid", body.get("message", "").lower())
        self.assertNotIn("target", body.get("message", "").lower())
        self.assertNotIn("session", body.get("message", "").lower())
        self.assertNotIn("pedido", body.get("message", "").lower())
        process_mock.assert_not_called()

    def test_pre_turn_loader_rejects_when_pedido_already_no_borrador(
        self,
    ) -> None:
        """The pre-turn loader is the only gate that enforces the
        ``borrador``-only eligibility contract. The post-turn
        snapshot loader is exempt by design. This test makes the
        asymmetry explicit by simulating a pre-turn loader
        rejection that mirrors the ``pedido not in borrador``
        branch — the route returns the documented generic
        rejection and never calls the processor.
        """
        # A pedido with estado_pedido != BORRADOR makes the real
        # pre-turn loader return None. To exercise the same path
        # in tests we patch the loader to None and assert the
        # processor is not called, mirroring the production branch
        # for "pedido ya no es borrador".
        with patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="42")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        # The body MUST NOT echo back the reason: an operator
        # probing the channel cannot tell apart "invalid id",
        # "missing pedido", "session missing" or "pedido not in
        # borrador" from this rejection.
        message_lower = body.get("message", "").lower()
        self.assertNotIn("borrador", message_lower)
        self.assertNotIn("ingresado", message_lower)
        self.assertNotIn("estado", message_lower)
        # The post-turn snapshot loader is NOT consulted on a
        # pre-turn rejection: there is nothing to project.
        process_mock.assert_not_called()


class PanelLocalTestRouteHappyPathTest(unittest.TestCase):
    """A valid local-test turn invokes the response orchestrator
    exactly once with the exact selected Session. No provider
    coordinator, no receipt, no outbox, no worker, no Twilio."""

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

    def _post(self):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=headers,
        )

    def test_happy_path_invokes_orchestrator_once_with_exact_session(self) -> None:
        exact_session = MagicMock(name="ExactSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = "product_selection"
        exact_session.pending_intents = None
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ) as loader, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = [
                CustomerResponse(
                    message="Hola, soy el cliente",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loader.call_count, 1)
        process_mock.assert_called_once()
        called_args = process_mock.call_args.args
        # Signature is ``process_incoming_message_with_responses(db, session, message)``
        # so the second positional must be the exact selected Session.
        self.assertIs(called_args[1], exact_session)
        self.assertEqual(called_args[2], "hola")
        body = response.json()
        self.assertEqual(
            body["responses"],
            [
                {
                    "message": "Hola, soy el cliente",
                    "intent": "saludo",
                    "status": "executed",
                }
            ],
        )
        self.assertIn("execution_state", body)
        execution_state = body["execution_state"]
        self.assertEqual(
            set(execution_state.keys()),
            {
                "context_type",
                "pending_encoding",
                "active_intent",
                "active_status",
                "candidate_count",
                "requirements_pending_count",
                "requirements_completed_count",
                "queue_length",
                "schema_version",
                "consistency",
            },
        )

    def test_happy_path_does_not_call_provider_outbox_worker(self) -> None:
        exact_session = MagicMock(name="ExactSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = None
        exact_session.pending_intents = None
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post()
        self.assertEqual(response.status_code, 200)
        # The route never imports or references the provider
        # coordinator, the worker or the outbox directly. The only
        # call into the message pipeline is the response
        # orchestrator for the exact selected session.
        self.assertEqual(process_mock.call_count, 1)


class PanelLocalTestRouteNoMutationTest(unittest.TestCase):
    """The route never commits, rolls back, flushes, refreshes,
    begins or closes the database session: the request-level
    dependency remains the transaction owner, and the existing
    transactional processor is the only commit/rollback authority
    for a valid turn."""

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

    def _post(self, *, body):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json=body,
            headers=headers,
        )

    def test_rejection_path_does_not_mutate_session(self) -> None:
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ):
            response = self._post(body={"message": "hola"})
        self.assertEqual(response.status_code, 400)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_happy_path_routes_through_orchestrator(self) -> None:
        exact_session = MagicMock(name="ExactSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = None
        exact_session.pending_intents = None
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_responses",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = [
                CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                )
            ]
            response = self._post(body={"message": "hola"})
        self.assertEqual(response.status_code, 200)


class PanelLocalTestRouteSrcPrivacyTest(unittest.TestCase):
    """The router file MUST NOT import any provider, Twilio, worker,
    outbound or receipt surface. The local-test POST handler is the
    only mutating entry point and only invokes the documented
    response orchestrator seam."""

    def test_router_source_does_not_import_provider_worker_twilio(self) -> None:
        from pathlib import Path

        forbidden = (
            "from backend.intents.handlers",
            "from backend.intents.context",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "from backend.llm",
            "from backend.services.session_service",
            "from backend.providers",
            "from backend.workers",
            "from backend.coordinators",
            "import requests",
            "import twilio",
            "MessagingResponse",
            "OutboundRow",
            "ProviderInboundMessageCoordinator",
            "ProviderReceipt",
        )
        source = Path(router_module.__file__).read_text(encoding="utf-8")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, source)


if __name__ == "__main__":
    unittest.main()
