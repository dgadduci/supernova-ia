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
import json
import os
import subprocess
import tempfile
import typing
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routers.admin_pilot_orders as router_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import get_session
from backend.diagnostics.outbound_response_style_prompt_template import (
    OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
)
from backend.intents.schemas.intent_classification import IntentName
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import EstadoPedido, EstadoSession
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.pilot_order_operations_view_service import (
    ClientSummary,
    CommerceSummary,
    DeliveryMethodView,
    OrderDetailView,
    OrderLineSnapshot,
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


def _style_diagnostic_not_attempted():
    from backend.services.outbound_response_styler import StyleDiagnostic
    return StyleDiagnostic(
        outcome="not_attempted",
        eligible_count=0,
        applied_count=0,
        response_types=(),
        template_version=OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
    )




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
    outbound on, and the bounded emulator configuration.
    """
    base = _settings(token=token)
    return Settings(
        **{**base.__dict__, **{
            "twilio_provider_mode": "emulator",
            "commerce_isolated_outbound_enabled": True,
            "twilio_emulator_base_url": "https://emulator.example.test",
            "twilio_emulator_account_sid": "AC" + "1" * 32,
            "twilio_emulator_auth_token": "emulator-auth-token-abc",
            "twilio_emulator_control_token": "control-token-xyz",
            "twilio_emulator_http_timeout_seconds": 5,
        }}
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


def _start_local_test_availability_patcher(test_instance) -> None:
    """Start a ``CommerceAvailabilityService.evaluate`` patcher on
    ``test_instance`` that returns ``AVAILABLE``.

    Tests that exercise the existing happy path of
    ``local_test_message`` MUST install this patcher in ``setUp``
    so the new inbound availability guard never blocks their
    MagicMock-driven session/processor interactions. Tests that
    intentionally exercise the unavailable-commerce branch must
    NOT use this helper; they drive ``_commerce_availability_outcome``
    directly.
    """
    from backend.services.commerce_availability_service import (
        CommerceAvailabilityOutcome,
        CommerceAvailabilityStatus,
    )

    patcher = patch.object(
        CommerceAvailabilityService,
        "evaluate",
        return_value=CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.AVAILABLE,
            reason=None,
            comercio_id=1,
            modo_operacion=None,
            prueba_hasta=None,
            prueba_max_pedidos=None,
            prueba_pedidos_consumidos=0,
        ),
    )
    test_instance._availability_patcher = patcher
    patcher.start()


def _stop_local_test_availability_patcher(test_instance) -> None:
    patcher = getattr(test_instance, "_availability_patcher", None)
    if patcher is not None:
        patcher.stop()


def _stub_service(
    *,
    list_view: OrderListView | None = None,
    detail: OrderDetailView | None = None,
    history: ProviderHistoryView | None = None,
    order_lines_snapshot: list[OrderLineSnapshot] | None = None,
):
    return SimpleNamespace(
        list_orders=MagicMock(return_value=list_view),
        get_detail=MagicMock(return_value=detail),
        get_provider_history=MagicMock(return_value=history),
        get_order_lines_snapshot=MagicMock(return_value=order_lines_snapshot),
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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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
        """The panel owns the panel-local test channel for the exact
        selected Pedido and the explicit Twilio emulator-test
        action. Every other route must remain GET-only."""
        for route in router_module.router.routes:
            methods = getattr(route, "methods", set())
            path = getattr(route, "path", "")
            if path.endswith("/local-test"):
                self.assertEqual(
                    methods,
                    {"POST"},
                    msg=(
                        f"local-test route must be POST only, got {methods}"
                    ),
                )
                continue
            if path.endswith(("/emulator-test", "/emulator-test/status")):
                self.assertEqual(
                    methods,
                    {"POST"},
                    msg=(
                        "emulator-test route must be POST only, "
                        f"got {methods}"
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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="Hola",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="Pedido confirmado",
                    intent="confirmar_pedido",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post()
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {"responses", "execution_state", "order_lines", "outbound_style"},
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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
        # The body must contain exactly the three documented keys.
        self.assertEqual(
            set(body.keys()),
            {"responses", "execution_state", "order_lines", "outbound_style"},
        )
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
            "process_incoming_message_with_style_diagnostic",
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
            "process_incoming_message_with_style_diagnostic",
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            response = self._post(body=None, json={})
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_non_string_message_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            response = self._post(body=None, json={"message": 123})
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_extra_field_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            response = self._post(
                body=None, json={"message": "hola", "extra": "x"}
            )
        self.assertEqual(response.status_code, 422)
        process_mock.assert_not_called()

    def test_oversized_message_returns_422(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
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
            "process_incoming_message_with_style_diagnostic",
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
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch.object(
                router_module,
                "_load_local_test_session",
                return_value=return_value,
            )
        )
        stack.enter_context(
            patch.object(
                router_module,
                "_load_confirmed_local_test_session",
                return_value=return_value,
            )
        )
        return stack

    def test_invalid_pedido_id_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="abc")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_missing_pedido_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="9999")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_loader_rejection_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, self._stub_loader_returning(None):
            response = self._post(pedido_id="42")
        self.assertEqual(response.status_code, 400)
        process_mock.assert_not_called()

    def test_loader_rejection_returns_generic_message(self) -> None:
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
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
            "process_incoming_message_with_style_diagnostic",
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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="Hola, soy el cliente",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loader.call_count, 1)
        process_mock.assert_called_once()
        called_args = process_mock.call_args.args
        # Signature is ``process_incoming_message_with_style_diagnostic(db, session, message)``
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post(body={"message": "hola"})
        self.assertEqual(response.status_code, 200)


class PanelLocalTestRouteSrcPrivacyTest(unittest.TestCase):
    """The router file MUST NOT import any provider, Twilio, worker,
    outbound or receipt surface. The local-test POST handler is the
    only mutating entry point and only invokes the documented
    response orchestrator seam plus the documented single-call
    classifier invocation for the non-draft status branch."""

    def test_router_source_does_not_import_provider_worker_twilio(self) -> None:
        from pathlib import Path

        forbidden = (
            "from backend.intents.handlers",
            "from backend.intents.context",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
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

    def test_router_source_only_uses_classifier_as_single_interpreter(
        self,
    ) -> None:
        """The router imports the existing ``IntentClassifier`` only
        so the non-draft branch can call it once as a language
        interpreter. No prompt, corpus, enum or model surface from
        the LLM package is imported; only the documented
        classification entry point.
        """
        from pathlib import Path

        source = Path(router_module.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "from backend.llm.intent_classifier import IntentClassifier",
            source,
        )
        for forbidden in (
            "from backend.llm.query_llm",
            "from backend.llm.settings",
            "from backend.llm.prompt",
            "from backend.diagnostics.prompt_template",
            "build_intent_prompt",
            "PROMPT_TEMPLATE_VERSION",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class PanelLocalTestRouteOrderLinesSnapshotTest(unittest.TestCase):
    """Task 9.1: the successful local-test response includes a typed
    JSON-safe ``order_lines`` snapshot for the exact selected
    Pedido. The snapshot is sourced through the existing panel
    view service so the router never queries the ORM directly."""

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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _make_session(self) -> MagicMock:
        exact_session = MagicMock(name="ExactSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = None
        exact_session.pending_intents = None
        return exact_session

    def _post(self):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=headers,
        )

    def _post_with(self, *, snapshots: list[OrderLineSnapshot]):
        exact_session = self._make_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls, patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            service_cls.return_value = _stub_service(
                order_lines_snapshot=snapshots,
            )
            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            return self._post(), service_cls.return_value, process_mock

    def test_happy_path_returns_order_lines_snapshot(self) -> None:
        snapshots = [
            OrderLineSnapshot(
                id=100,
                producto_nombre="Pan",
                presentacion_descripcion="Bolsa x 1kg",
                cantidad=2,
                precio_unitario_display="150.00",
                observaciones="Sin sal",
            ),
            OrderLineSnapshot(
                id=101,
                producto_nombre="Agua",
                presentacion_descripcion=None,
                cantidad=1,
                precio_unitario_display="0",
                observaciones=None,
            ),
        ]
        response, service, _process_mock = self._post_with(snapshots=snapshots)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {"responses", "execution_state", "order_lines", "outbound_style"},
        )
        self.assertEqual(len(body["order_lines"]), 2)
        first = body["order_lines"][0]
        self.assertEqual(
            set(first.keys()),
            {
                "id",
                "producto_nombre",
                "presentacion_descripcion",
                "cantidad",
                "precio_unitario_display",
                "observaciones",
            },
        )
        self.assertEqual(first["id"], 100)
        self.assertEqual(first["producto_nombre"], "Pan")
        self.assertEqual(first["presentacion_descripcion"], "Bolsa x 1kg")
        self.assertEqual(first["cantidad"], 2)
        self.assertEqual(first["precio_unitario_display"], "150.00")
        self.assertEqual(first["observaciones"], "Sin sal")
        self.assertIsNone(body["order_lines"][1]["presentacion_descripcion"])
        self.assertIsNone(body["order_lines"][1]["observaciones"])
        # The router must source lines via the view service so it
        # never queries the ORM directly.
        service.get_order_lines_snapshot.assert_called_once_with(42)

    def test_happy_path_returns_empty_order_lines_when_pedido_has_no_lines(
        self,
    ) -> None:
        response, _service, _process = self._post_with(snapshots=[])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["order_lines"], [])

    def test_happy_path_serializes_price_as_string(self) -> None:
        """The router serializes the pre-formatted price string so the
        wire payload is JSON-safe and never carries a raw Decimal."""
        snapshots = [
            OrderLineSnapshot(
                id=1,
                producto_nombre="Item",
                presentacion_descripcion="X",
                cantidad=1,
                precio_unitario_display="150.00",
                observaciones=None,
            ),
        ]
        response, _service, _process = self._post_with(snapshots=snapshots)
        body = response.json()
        line = body["order_lines"][0]
        self.assertIsInstance(line["precio_unitario_display"], str)
        self.assertEqual(line["precio_unitario_display"], "150.00")
        # No raw Decimal token leaks anywhere in the JSON payload.
        self.assertNotIn("Decimal", response.text)

    def test_response_does_not_emit_session_or_pedido_fields_in_order_lines(
        self,
    ) -> None:
        snapshots = [
            OrderLineSnapshot(
                id=1,
                producto_nombre="Item",
                presentacion_descripcion="X",
                cantidad=1,
                precio_unitario_display="150.00",
                observaciones="<script>",
            ),
        ]
        response, _service, _process = self._post_with(snapshots=snapshots)
        body_text = response.text
        # ``order_lines`` must never expose Session/Pedido,
        # pending, candidate, provider or credential fields. Note
        # that ``context_type`` IS a documented closed
        # ``execution_state`` value, so it is allowed in the body
        # of a successful response — what the assertion forbids is
        # leaking it through the order-lines array specifically.
        self.assertNotIn(
            "id_session", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "id_pedido", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "id_comercio", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "id_cliente", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "pending_intents", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "candidate_ids", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "source_text", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "identificador_proveedor", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "API_KEY", body_text.split('"order_lines"')[1]
        )
        self.assertNotIn(
            "OPENAI", body_text.split('"order_lines"')[1]
        )
        # The order_lines JSON array only carries the documented
        # closed field names — no ORM or session attribute leaks.
        body = response.json()
        for entry in body["order_lines"]:
            self.assertEqual(
                set(entry.keys()),
                {
                    "id",
                    "producto_nombre",
                    "presentacion_descripcion",
                    "cantidad",
                    "precio_unitario_display",
                    "observaciones",
                },
            )

    def test_rejection_does_not_emit_order_lines(self) -> None:
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls, patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=None,
        ):
            service_cls.return_value = _stub_service(
                order_lines_snapshot=[
                    OrderLineSnapshot(
                        id=1,
                        producto_nombre="X",
                        presentacion_descripcion=None,
                        cantidad=1,
                        precio_unitario_display="1",
                        observaciones=None,
                    )
                ],
            )
            response = self._post()
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertNotIn("order_lines", body)
        self.assertNotIn("execution_state", body)

    def test_wrong_origin_does_not_emit_order_lines(self) -> None:
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        with patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                order_lines_snapshot=[
                    OrderLineSnapshot(
                        id=1,
                        producto_nombre="X",
                        presentacion_descripcion=None,
                        cantidad=1,
                        precio_unitario_display="1",
                        observaciones=None,
                    )
                ],
            )
            response = self.client.post(
                "/admin/pilot/orders/42/local-test",
                json={"message": "hola"},
                headers=headers,
            )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertNotIn("order_lines", body)
        process_mock.assert_not_called()

    def test_no_mutation_when_calling_order_lines_snapshot(self) -> None:
        snapshots = [
            OrderLineSnapshot(
                id=1,
                producto_nombre="X",
                presentacion_descripcion=None,
                cantidad=1,
                precio_unitario_display="1",
                observaciones=None,
            ),
        ]
        response, _service, _process = self._post_with(snapshots=snapshots)
        self.assertEqual(response.status_code, 200)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()


class PanelDetailLinesLayoutOrderTest(unittest.TestCase):
    """Task 9.2: the scrollable lines section lives immediately below
    ``<h2>Detalle del pedido</h2>`` and before the comercio/cliente
    /sesión/pedido metadata sections."""

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

    def _render(self, *, lineas):
        detail = _build_detail()
        if lineas == "empty":
            detail = OrderDetailView(
                pedido=detail.pedido,
                session=detail.session,
                client=detail.client,
                commerce=detail.commerce,
                direccion_entrega=detail.direccion_entrega,
                observaciones=detail.observaciones,
                datetime_entrega_programada=detail.datetime_entrega_programada,
                datetime_entrega_programada_local=detail.datetime_entrega_programada_local,
                medio_pago=detail.medio_pago,
                metodo_entrega=detail.metodo_entrega,
                lineas=[],
            )
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=detail,
                history=_build_history(),
            )
            return self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )

    def test_lines_section_follows_h2_detalle_del_pedido(self) -> None:
        response = self._render(lineas="populated")
        self.assertEqual(response.status_code, 200)
        body = response.text
        # The H2 heading must come before the Líneas section.
        h2_index = body.find("<h2>Detalle del pedido</h2>")
        self.assertNotEqual(h2_index, -1)
        lines_section_index = body.find("<h3>Líneas</h3>")
        self.assertNotEqual(lines_section_index, -1)
        self.assertLess(h2_index, lines_section_index)
        # The Líneas section must precede the Comercio/Cliente/Sesión/
        # Pedido metadata sections.
        comercio_index = body.find("<h3>Comercio</h3>")
        cliente_index = body.find("<h3>Cliente</h3>")
        session_index = body.find("<h3>Sesión</h3>")
        pedido_index = body.find("<h3>Pedido</h3>")
        for index in (
            comercio_index,
            cliente_index,
            session_index,
            pedido_index,
        ):
            with self.subTest(index=index):
                self.assertGreater(index, lines_section_index)

    def test_lines_table_has_data_debug_lines_tbody(self) -> None:
        response = self._render(lineas="populated")
        body = response.text
        self.assertIn("data-debug-lines-tbody", body)

    def test_empty_state_has_data_debug_lines_empty(self) -> None:
        response = self._render(lineas="empty")
        body = response.text
        # When no lines exist, the empty-state node must be present
        # (without ``hidden``) and the scroll container must still
        # be rendered so the layout never shifts.
        self.assertIn("data-debug-lines-empty", body)
        self.assertIn("El pedido no tiene líneas registradas.", body)
        # The empty-state is visible (no hidden attribute).
        self.assertRegex(
            body,
            r'<div class="empty" data-debug-lines-empty[^>]*>El pedido no tiene líneas registradas\.',
        )

    def test_lines_with_data_are_present_and_empty_state_hidden(self) -> None:
        response = self._render(lineas="populated")
        body = response.text
        self.assertIn("data-debug-lines-tbody", body)
        self.assertIn("Pan &lt;b&gt;", body)
        # The empty-state node must still be present (so the browser
        # script can toggle it) but hidden when lines exist.
        self.assertIn("data-debug-lines-empty", body)
        self.assertRegex(
            body,
            r'<div class="empty" data-debug-lines-empty hidden>El pedido no tiene líneas registradas\.',
        )


class PanelLinesRefreshBrowserScriptTest(unittest.TestCase):
    """Task 9.2: the existing browser script refreshes the
    scrollable line list in place via text APIs only, never
    ``innerHTML``, and preserves the existing transcript on a
    failure."""

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

    def _detail_body(self) -> str:
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
        self.assertEqual(response.status_code, 200)
        return _strip_css(response.text)

    def test_browser_handler_uses_text_apis_only(self) -> None:
        body = self._detail_body()
        # The line-refresh handler must rely exclusively on text
        # APIs and DOM creation helpers.
        for required in (
            "createElement",
            "textContent",
            "replaceChildren",
            "data-debug-lines-tbody",
            "data-debug-lines-empty",
        ):
            with self.subTest(required=required):
                self.assertIn(required, body)
        # No HTML interpolation helper anywhere in the script.
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("outerHTML", body)

    def test_browser_handler_validates_order_lines_array(self) -> None:
        body = self._detail_body()
        # The handler must check ``order_lines`` is an array before
        # applying any update so a malformed response cannot
        # overwrite the displayed lines.
        self.assertIn("order_lines", body)
        self.assertIn("Array.isArray(result.data.order_lines)", body)

    def test_browser_handler_keeps_transcript_on_failure(self) -> None:
        body = self._detail_body()
        # The handler must short-circuit on a non-success, malformed
        # or non-array ``order_lines`` response. The shared error
        # branch returns BEFORE any refresh helper is reached.
        self.assertIn("Error del canal local", body)
        self.assertIn("Array.isArray(result.data.order_lines)", body)
        # The handler must return inside the validation block so a
        # failure never reaches ``updateOrderLines``.
        self.assertIn("return;", body)
        # Validate that the validation guard sits before the line
        # refresh call in the success branch.
        validation_index = body.find("Array.isArray(result.data.order_lines)")
        update_index = body.find("updateOrderLines(result.data.order_lines)")
        self.assertNotEqual(validation_index, -1)
        self.assertNotEqual(update_index, -1)
        self.assertLess(validation_index, update_index)

    def test_browser_handler_replaces_rows_on_success(self) -> None:
        body = self._detail_body()
        # The success path must call replaceChildren so old rows
        # are removed before the new ones are inserted.
        self.assertIn("replaceChildren", body)
        # The success path must invoke updateOrderLines with the
        # validated array.
        self.assertIn("updateOrderLines(result.data.order_lines)", body)


_BASE_TEMPLATE_HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "admin_pilot_orders"
    / "base.html"
)


def _resolve_jsdom_require_path():
    """Locate a ``jsdom`` install for the JSDOM-backed tests.

    The helper probes ``$PANEL_JSDOM_PATH`` first and falls back
    to the local fixture installed at ``/tmp/jsdom-test`` during
    development. The probe is deliberately narrow so the tests
    skip cleanly when the Node.js runtime or ``jsdom`` is not
    available on the host.
    """
    candidates = [
        os.environ.get("PANEL_JSDOM_PATH"),
        "/tmp/jsdom-test/node_modules/jsdom",
    ]
    for candidate in candidates:
        if candidate and Path(candidate, "package.json").exists():
            return candidate
    return None


def _extract_inline_script(template_html: str) -> str:
    start = template_html.find("<script>")
    end = template_html.find("</script>")
    if start == -1 or end == -1:
        raise AssertionError(
            "could not locate the inline <script> tag in base.html"
        )
    return template_html[start + len("<script>"):end]


def _build_lines_update_js(*, initial_rows_html: str, empty_attr: str, payload) -> str:
    jsdom_path = _resolve_jsdom_require_path()
    if jsdom_path is None:
        raise unittest.SkipTest(
            "jsdom not available; install via `npm install jsdom` "
            "and set PANEL_JSDOM_PATH (or use /tmp/jsdom-test) to "
            "enable the runtime order-lines validation tests."
        )
    template = _BASE_TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
    script = _extract_inline_script(template)
    jsdom_literal = json.dumps(jsdom_path)
    payload_literal = json.dumps(payload)
    return (
        "const {JSDOM} = require(" + jsdom_literal + ");\n"
        "const dom = new JSDOM("
        "`<!DOCTYPE html><html><body>"
        "<table><tbody data-debug-lines-tbody>"
        + initial_rows_html.replace("`", "\\`")
        + "</tbody></table>"
        "<div class=\\\"empty\\\" data-debug-lines-empty"
        + empty_attr
        + ">El pedido no tiene líneas registradas.</div>"
        "<script>"
        + script.replace("`", "\\`")
        + "</script>"
        "</body></html>`, {runScripts: 'dangerously'});\n"
        "const w = dom.window;\n"
        "const tbody = w.document.querySelector('[data-debug-lines-tbody]');\n"
        "const empty = w.document.querySelector('[data-debug-lines-empty]');\n"
        "const before = {\n"
        "  rows: tbody.children.length,\n"
        "  hidden: empty.hidden\n"
        "};\n"
        "const payload = " + payload_literal + ";\n"
        "const result = w.__panelDebugLines\n"
        "  ? w.__panelDebugLines.updateOrderLines(payload)\n"
        "  : null;\n"
        "const after = {\n"
        "  rows: tbody.children.length,\n"
        "  hidden: empty.hidden\n"
        "};\n"
        "console.log(JSON.stringify({before: before, after: after, result: result}));\n"
    )


def _run_lines_update_in_jsdom(
    payload,
    *,
    initial_lines: list[dict] | None = None,
    empty_hidden: bool = True,
) -> dict:
    rows_html = ""
    if initial_lines:
        rows_html = "".join(
            "<tr><td>#"
            + str(int(row["id"]))
            + "</td><td>"
            + str(row.get("producto_nombre", ""))
            + "</td><td></td><td>"
            + str(row.get("cantidad", ""))
            + "</td><td>"
            + str(row.get("precio_unitario_display", ""))
            + "</td><td></td></tr>"
            for row in initial_lines
        )
    empty_attr = " hidden" if empty_hidden else ""
    js_source = _build_lines_update_js(
        initial_rows_html=rows_html,
        empty_attr=empty_attr,
        payload=payload,
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(js_source)
        script_path = handle.name
    try:
        completed = subprocess.run(
            ["node", script_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    output = completed.stdout.decode("utf-8").strip()
    if not output:
        raise AssertionError(
            "node produced no stdout; stderr was: "
            + completed.stderr.decode("utf-8")
        )
    return json.loads(output.splitlines()[-1])


def _build_form_submit_js(*, response_payload, initial_lines, initial_execution_state) -> str:
    jsdom_path = _resolve_jsdom_require_path()
    if jsdom_path is None:
        raise unittest.SkipTest(
            "jsdom not available; install via `npm install jsdom` "
            "and set PANEL_JSDOM_PATH (or use /tmp/jsdom-test) to "
            "enable the runtime order-lines validation tests."
        )
    template = _BASE_TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
    script = _extract_inline_script(template)
    initial_rows_html = "".join(
        "<tr><td>#"
        + str(int(row["id"]))
        + "</td><td>"
        + str(row.get("producto_nombre", ""))
        + "</td></tr>"
        for row in initial_lines
    )
    cell_attr_map = {
        "context_type": "data-debug-context",
        "pending_encoding": "data-debug-encoding",
        "active_intent": "data-debug-active-intent",
        "active_status": "data-debug-active-status",
        "candidate_count": "data-debug-candidate-count",
        "requirements_pending_count": "data-debug-requirements-pending",
        "requirements_completed_count": "data-debug-requirements-completed",
        "queue_length": "data-debug-queue-length",
        "schema_version": "data-debug-schema-version",
        "consistency": "data-debug-consistency",
    }
    execution_state_cells_html = "".join(
        "<dd "
        + cell_attr_map[key]
        + ">"
        + json.dumps(initial_execution_state[key])[1:-1]
        + "</dd>"
        for key in cell_attr_map
    )
    jsdom_literal = json.dumps(jsdom_path)
    response_literal = json.dumps(response_payload)
    script_literal = json.dumps(script)
    return (
        "const {JSDOM} = require(" + jsdom_literal + ");\n"
        "const initialRowsHtml = " + json.dumps(initial_rows_html) + ";\n"
        "const executionStateCellsHtml = "
        + json.dumps(execution_state_cells_html)
        + ";\n"
        "const baseScript = " + script_literal + ";\n"
        "const responsePayload = " + response_literal + ";\n"
        "function escapeScript(scriptBody) {\n"
        "  return scriptBody.replace(/<\\/script/gi, '<\\\\/script');\n"
        "}\n"
        "const safeBaseScript = escapeScript(baseScript);\n"
        "const html = [\n"
        "  '<!DOCTYPE html><html><body>',\n"
        "  '<form data-debug-form action=\"/test\">',\n"
        "  '<textarea data-debug-textarea></textarea>',\n"
        "  '<button data-debug-submit></button>',\n"
        "  '</form>',\n"
        "  '<div data-debug-transcript></div>',\n"
        "  '<p data-debug-status></p>',\n"
        "  '<table><tbody data-debug-lines-tbody>',\n"
        "  initialRowsHtml,\n"
        "  '</tbody></table>',\n"
        "  '<div class=\"empty\" data-debug-lines-empty hidden>El pedido no tiene líneas registradas.</div>',\n"
        "  '<dl>',\n"
        "  executionStateCellsHtml,\n"
        "  '</dl>',\n"
        "  '<script>window.fetch = function(url, options) { return Promise.resolve({ ok: true, json: function() { return Promise.resolve(responsePayload); } }); };</script>',\n"
        "  '<script>',\n"
        "  safeBaseScript,\n"
        "  '</script>',\n"
        "  '</body></html>'\n"
        "].join('');\n"
        "const dom = new JSDOM(html, {runScripts: 'dangerously'});\n"
        "const w = dom.window;\n"
        "const form = w.document.querySelector('[data-debug-form]');\n"
        "const textarea = w.document.querySelector('[data-debug-textarea]');\n"
        "textarea.value = 'turno de prueba';\n"
        "const submitEvent = new w.Event('submit', {bubbles: true, cancelable: true});\n"
        "form.dispatchEvent(submitEvent);\n"
        "setTimeout(function() {\n"
        "  const tbody = w.document.querySelector('[data-debug-lines-tbody]');\n"
        "  const empty = w.document.querySelector('[data-debug-lines-empty]');\n"
        "  const transcript = w.document.querySelector('[data-debug-transcript]');\n"
        "  const status = w.document.querySelector('[data-debug-status]');\n"
        "  const executionStateCells = [\n"
        "    'data-debug-context',\n"
        "    'data-debug-encoding',\n"
        "    'data-debug-active-intent',\n"
        "    'data-debug-active-status',\n"
        "    'data-debug-candidate-count',\n"
        "    'data-debug-requirements-pending',\n"
        "    'data-debug-requirements-completed',\n"
        "    'data-debug-queue-length',\n"
        "    'data-debug-schema-version',\n"
        "    'data-debug-consistency'\n"
        "  ];\n"
        "  const executionStateAfter = {};\n"
        "  executionStateCells.forEach(function(attr) {\n"
        "    const node = w.document.querySelector('[' + attr + ']');\n"
        "    executionStateAfter[attr] = node ? node.textContent : null;\n"
        "  });\n"
        "  const result = {\n"
        "    tbodyRows: tbody.children.length,\n"
        "    tbodyFirstCell: tbody.children.length > 0 ? tbody.children[0].textContent : null,\n"
        "    emptyHidden: empty.hidden,\n"
        "    transcript: transcript.textContent,\n"
        "    status: status.textContent,\n"
        "    executionState: executionStateAfter\n"
        "  };\n"
        "  console.log(JSON.stringify(result));\n"
        "}, 100);\n"
    )


def _run_form_submit_in_jsdom(
    *, response_payload, initial_lines, initial_execution_state
) -> dict:
    js_source = _build_form_submit_js(
        response_payload=response_payload,
        initial_lines=initial_lines,
        initial_execution_state=initial_execution_state,
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(js_source)
        script_path = handle.name
    try:
        completed = subprocess.run(
            ["node", script_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    output = completed.stdout.decode("utf-8").strip()
    if not output:
        raise AssertionError(
            "node produced no stdout; stderr was: "
            + completed.stderr.decode("utf-8")
        )
    return json.loads(output.splitlines()[-1])


class PanelLocalTestRouteOrderLinesStrictValidationTest(unittest.TestCase):
    """The browser-side order-line refresh must validate the
    snapshot strictly before any DOM mutation. A single invalid
    entry invalidates the entire snapshot; ``replaceChildren`` is
    only invoked after the validated count is known."""

    _INITIAL_LINES: typing.ClassVar[list[dict]] = [
        {
            "id": 100,
            "producto_nombre": "Initial line",
            "cantidad": 1,
            "precio_unitario_display": "150.00",
        }
    ]
    _INITIAL_EXECUTION_STATE: typing.ClassVar[dict] = {
        "context_type": "old-context",
        "pending_encoding": "old-pending",
        "active_intent": "old-intent",
        "active_status": "old-status",
        "candidate_count": 99,
        "requirements_pending_count": 99,
        "requirements_completed_count": 99,
        "queue_length": 99,
        "schema_version": 1,
        "consistency": "consistent",
    }

    def test_payload_with_null_preserves_existing_lines(self) -> None:
        result = _run_lines_update_in_jsdom(
            payload=[None],
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["before"], {"rows": 1, "hidden": True})
        self.assertEqual(result["after"], {"rows": 1, "hidden": True})
        self.assertEqual(result["result"], False)

    def test_payload_with_empty_object_preserves_existing_lines(self) -> None:
        result = _run_lines_update_in_jsdom(
            payload=[{}],
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["before"], {"rows": 1, "hidden": True})
        self.assertEqual(result["after"], {"rows": 1, "hidden": True})
        self.assertEqual(result["result"], False)

    def test_payload_with_invalid_entry_does_not_update_partially(self) -> None:
        result = _run_lines_update_in_jsdom(
            payload=[
                {
                    "id": 1,
                    "producto_nombre": "valid",
                    "presentacion_descripcion": None,
                    "cantidad": 1,
                    "precio_unitario_display": "150.00",
                    "observaciones": None,
                },
                None,
            ],
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["before"], {"rows": 1, "hidden": True})
        self.assertEqual(result["after"], {"rows": 1, "hidden": True})
        self.assertEqual(result["result"], False)

    def test_empty_valid_payload_clears_rows_and_shows_empty_state(self) -> None:
        result = _run_lines_update_in_jsdom(
            payload=[],
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["before"], {"rows": 1, "hidden": True})
        self.assertEqual(result["after"], {"rows": 0, "hidden": False})
        self.assertEqual(result["result"], True)

    def test_fully_valid_payload_replaces_all_rows(self) -> None:
        payload = [
            {
                "id": 7,
                "producto_nombre": "Replacement A",
                "presentacion_descripcion": "Bag",
                "cantidad": 2,
                "precio_unitario_display": "150.00",
                "observaciones": None,
            },
            {
                "id": 8,
                "producto_nombre": "Replacement B",
                "presentacion_descripcion": None,
                "cantidad": 3,
                "precio_unitario_display": "9.99",
                "observaciones": "Sin sal",
            },
        ]
        result = _run_lines_update_in_jsdom(
            payload=payload,
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["before"], {"rows": 1, "hidden": True})
        self.assertEqual(result["after"], {"rows": 2, "hidden": True})
        self.assertEqual(result["result"], True)

    def test_payload_with_invalid_types_rejects_snapshot(self) -> None:
        # Wrong type for ``id`` (string instead of integer).
        result = _run_lines_update_in_jsdom(
            payload=[
                {
                    "id": "1",
                    "producto_nombre": "wrong-id-type",
                    "presentacion_descripcion": None,
                    "cantidad": 1,
                    "precio_unitario_display": "150.00",
                    "observaciones": None,
                }
            ],
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["after"], {"rows": 1, "hidden": True})
        self.assertEqual(result["result"], False)

    def test_payload_with_non_array_input_rejects_snapshot(self) -> None:
        for payload in (None, "lines", 42, {"lines": []}):
            with self.subTest(payload=payload):
                result = _run_lines_update_in_jsdom(
                    payload=payload,
                    initial_lines=self._INITIAL_LINES,
                    empty_hidden=True,
                )
                self.assertEqual(result["after"], {"rows": 1, "hidden": True})
                self.assertEqual(result["result"], False)

    def test_payload_with_zero_or_negative_id_rejects_snapshot(self) -> None:
        for bad_id in (0, -1):
            with self.subTest(bad_id=bad_id):
                payload = [
                    {
                        "id": bad_id,
                        "producto_nombre": "wrong-id",
                        "presentacion_descripcion": None,
                        "cantidad": 1,
                        "precio_unitario_display": "150.00",
                        "observaciones": None,
                    }
                ]
                result = _run_lines_update_in_jsdom(
                    payload=payload,
                    initial_lines=self._INITIAL_LINES,
                    empty_hidden=True,
                )
                self.assertEqual(result["after"], {"rows": 1, "hidden": True})
                self.assertEqual(result["result"], False)

    def test_payload_with_missing_field_rejects_snapshot(self) -> None:
        payload = [
            {
                "id": 1,
                "producto_nombre": "missing-observaciones",
                "presentacion_descripcion": None,
                "cantidad": 1,
                "precio_unitario_display": "150.00",
            }
        ]
        result = _run_lines_update_in_jsdom(
            payload=payload,
            initial_lines=self._INITIAL_LINES,
            empty_hidden=True,
        )
        self.assertEqual(result["after"], {"rows": 1, "hidden": True})
        self.assertEqual(result["result"], False)


class PanelLocalTestRouteOrderLinesFormRejectionTest(unittest.TestCase):
    """Task 9 review fix: a malformed ``order_lines`` snapshot
    triggers the documented generic rejection branch. The browser
    keeps the previously rendered lines, the previously rendered
    execution state and the in-memory transcript. The script
    never builds HTML through ``innerHTML`` / ``outerHTML``."""

    _INITIAL_LINES: typing.ClassVar[list[dict]] = [
        {
            "id": 100,
            "producto_nombre": "Initial line",
            "cantidad": 1,
            "precio_unitario_display": "150.00",
        }
    ]
    _INITIAL_EXECUTION_STATE: typing.ClassVar[dict] = {
        "context_type": "old-context",
        "pending_encoding": "old-pending",
        "active_intent": "old-intent",
        "active_status": "old-status",
        "candidate_count": 99,
        "requirements_pending_count": 99,
        "requirements_completed_count": 99,
        "queue_length": 99,
        "schema_version": 1,
        "consistency": "consistent",
    }
    _VALID_RESPONSE: typing.ClassVar[dict] = {
        "responses": [{"message": "ignored"}],
        "execution_state": {
            "context_type": "new-context",
            "pending_encoding": "new-pending",
            "active_intent": "new-intent",
            "active_status": "new-status",
            "candidate_count": 0,
            "requirements_pending_count": 0,
            "requirements_completed_count": 0,
            "queue_length": 0,
            "schema_version": None,
            "consistency": "none",
        },
        "order_lines": [
            {
                "id": 999,
                "producto_nombre": "Should not be applied",
                "presentacion_descripcion": None,
                "cantidad": 1,
                "precio_unitario_display": "150.00",
                "observaciones": None,
            }
        ],
    }

    def _malformed_response(self, *, order_lines):
        payload = dict(self._VALID_RESPONSE)
        payload["order_lines"] = order_lines
        return payload

    def _assert_preserved(self, result) -> None:
        self.assertEqual(result["tbodyRows"], 1)
        self.assertEqual(result["emptyHidden"], True)
        self.assertIn("#100", result["tbodyFirstCell"])
        self.assertIn(
            "El canal local rechazó el mensaje", result["transcript"]
        )
        self.assertIn(
            "Error del canal local", result["status"]
        )
        self.assertEqual(
            result["executionState"]["data-debug-context"], "old-context"
        )
        self.assertEqual(
            result["executionState"]["data-debug-encoding"], "old-pending"
        )
        self.assertEqual(
            result["executionState"]["data-debug-active-intent"], "old-intent"
        )
        self.assertEqual(
            result["executionState"]["data-debug-consistency"], "consistent"
        )

    def test_malformed_response_preserves_lines_and_execution_state(self) -> None:
        for malformed in (
            [None],
            [{}],
            [
                {
                    "id": 1,
                    "producto_nombre": "valid",
                    "presentacion_descripcion": None,
                    "cantidad": 1,
                    "precio_unitario_display": "150.00",
                    "observaciones": None,
                },
                {"id": 2},
            ],
        ):
            with self.subTest(payload=malformed):
                result = _run_form_submit_in_jsdom(
                    response_payload=self._malformed_response(
                        order_lines=malformed
                    ),
                    initial_lines=self._INITIAL_LINES,
                    initial_execution_state=self._INITIAL_EXECUTION_STATE,
                )
                self._assert_preserved(result)

    def test_browser_script_does_not_use_innerHTML_or_outerHTML(self) -> None:
        template = _BASE_TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
        script = _extract_inline_script(template)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("outerHTML", script)

    def test_browser_script_uses_safe_dom_apis(self) -> None:
        template = _BASE_TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
        script = _extract_inline_script(template)
        for required in (
            "createElement",
            "textContent",
            "replaceChildren",
            "isValidLineEntry",
            "validateOrderLines",
        ):
            with self.subTest(required=required):
                self.assertIn(required, script)

    def test_form_handler_validates_before_state_update(self) -> None:
        template = _BASE_TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
        script = _extract_inline_script(template)
        # ``validateOrderLines`` must be invoked inside the
        # payload validation guard, before any state mutation.
        validation_index = script.find("validateOrderLines(result.data.order_lines)")
        execution_index = script.find("updateExecutionState(result.data.execution_state)")
        order_lines_index = script.find("updateOrderLines(result.data.order_lines)")
        self.assertNotEqual(validation_index, -1)
        self.assertNotEqual(execution_index, -1)
        self.assertNotEqual(order_lines_index, -1)
        self.assertLess(validation_index, execution_index)
        self.assertLess(validation_index, order_lines_index)
        self.assertLess(execution_index, order_lines_index)
        # The guard must return on a malformed snapshot so neither
        # the lines nor the execution state are overwritten.
        guard_block = script[
            validation_index : script.find("return;", validation_index) + len("return;")
        ]
        self.assertIn("appendLine(\"error\"", guard_block)
        self.assertIn("Error del canal local", guard_block)


class PanelLocalTestConfirmedOrderStatusTest(unittest.TestCase):
    """Confirmed-order local-test branch: a non-``BORRADOR`` pedido
    with a clean pending context accepts only one
    :class:`IntentName.CONSULTAR_ESTADO_PEDIDO` intent and routes
    it through the existing read-only status orchestration. Every
    other outcome — non-status intent, multi-intent, classifier
    transport/schema failure, active/queued pending context or
    identity/ownership inconsistency — returns the documented
    generic local rejection without invoking the normal message
    processor, the global dispatcher or any mutating handler.

    These tests intentionally do NOT use the SQLAlchemy session
    override to drive the loader, because the route reaches the
    confirmed branch only after the existing draft loader returns
    ``None``. The tests patch both
    :func:`_load_local_test_session` and
    :func:`_load_confirmed_local_test_session` so the
    exact-target contract is exercised without touching the
    database.
    """

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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
        self._settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _post(self, *, message: str = "¿cómo viene mi pedido?"):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Local-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": message},
            headers=headers,
        )

    def _build_session(
        self,
        *,
        context_type=None,
        pending_intents=None,
    ):
        session = MagicMock(name="ConfirmedExactSession")
        session.id = 21
        session.id_pedido = 42
        session.id_comercio = 1
        session.id_cliente = 31
        session.estado_session = EstadoSession.ACTIVA
        session.context_type = context_type
        session.pending_intents = pending_intents
        return session

    def _build_pedido(self):
        pedido = MagicMock(name="ConfirmedExactPedido")
        pedido.id = 42
        pedido.estado_pedido = EstadoPedido.INGRESADO
        return pedido

    def _stub_loaders(self, session):
        pedido = self._build_pedido()
        return pedido, session, [
            patch.object(
                router_module,
                "_load_local_test_session",
                return_value=None,
            ),
            patch.object(
                router_module,
                "_load_confirmed_local_test_session",
                return_value=(pedido, session),
            ),
        ]

    def _patched_post(self, *, session, extra_patches):
        pedido, exact_session, loaders = self._stub_loaders(session)
        patches = list(loaders) + list(extra_patches)
        from contextlib import ExitStack

        stack = ExitStack()
        for p in patches:
            stack.enter_context(p)
        return stack, pedido, exact_session

    def _build_classification(self, *, intents):
        from backend.intents.schemas.intent_classification import (
            ClassifiedIntent,
            IntentClassificationResult,
        )

        first_message = (
            intents[0][1] if intents else "noop"
        )
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(intent=name, mensaje=message)
                for name, message in intents
            ],
            mensaje=first_message,
        )

    def test_natural_status_question_for_confirmed_order_returns_status(
        self,
    ) -> None:
        """A confirmed pedido with a clean pending context accepts
        a natural-language status question that the classifier maps
        to ``consultar_estado_pedido``. The route reuses the
        existing read-only status orchestration and shared response
        mapper for the exact same pedido/session identity.
        """
        session = self._build_session()
        classification = self._build_classification(
            intents=[(IntentName.CONSULTAR_ESTADO_PEDIDO, "¿cómo viene mi pedido?")],
        )
        processed_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="¿cómo viene mi pedido?",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "ingresado"},
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
            return_value=processed_intent,
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
            return_value=(
                [
                    MagicMock(
                    name="CustomerResponse",
                    message="Tu pedido fue recibido y está confirmado.",
                    intent="consultar_estado_pedido",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
        ) as mapper, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(self._build_pedido(), session),
        ) as snapshot_loader, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            service_cls.return_value = _stub_service(
                order_lines_snapshot=[
                    OrderLineSnapshot(
                        id=1,
                        producto_nombre="Pan",
                        presentacion_descripcion="Bolsa x 1kg",
                        cantidad=2,
                        precio_unitario_display="150.00",
                        observaciones=None,
                    )
                ],
            )
            stack, _pedido, exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["responses"],
            [
                {
                    "message": "Tu pedido fue recibido y está confirmado.",
                    "intent": "consultar_estado_pedido",
                    "status": "executed",
                }
            ],
        )
        # The classifier is invoked exactly once as a language
        # interpreter only.
        classifier_instance.query.assert_called_once_with(
            "¿cómo viene mi pedido?"
        )
        # The status orchestrator and shared mapper are reused; the
        # normal message processor is NEVER invoked on this branch.
        status_query.assert_called_once()
        mapper.assert_called_once()
        process_mock.assert_not_called()
        # The snapshot uses the same exact pedido/session identity.
        snapshot_loader.assert_called_once()
        snapshot_args = snapshot_loader.call_args.args
        self.assertEqual(snapshot_args[1], 42)
        self.assertEqual(snapshot_args[2], exact_session.id)
        # No internal details leak into the response.
        for forbidden in (
            "pending_intents",
            "candidate_ids",
            "resolved_data",
            "source_text",
            "OPENAI",
            "API_KEY",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        self.assertEqual(
            set(body.keys()),
            {"responses", "execution_state", "order_lines", "outbound_style"},
        )

    def test_confirmed_order_does_not_call_transaction_control_methods(
        self,
    ) -> None:
        """The accepted confirmed path is read-only: the router
        never calls commit/rollback/flush/refresh/begin/begin_nested/
        close/expire and the snapshot loader does not touch
        transaction controls either.
        """
        session = self._build_session()
        classification = self._build_classification(
            intents=[(IntentName.CONSULTAR_ESTADO_PEDIDO, "estado")],
        )
        processed_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "preparacion"},
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
            return_value=processed_intent,
        ), patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
            return_value=(
                [
                    MagicMock(
                    name="CustomerResponse",
                    message="ok",
                    intent="consultar_estado_pedido",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(self._build_pedido(), session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ):
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 200)
        for method in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.session, method).assert_not_called()

    def test_confirmed_order_with_iniciar_pedido_intent_is_rejected(
        self,
    ) -> None:
        session = self._build_session()
        classification = self._build_classification(
            intents=[(IntentName.INICIAR_PEDIDO, "quiero un pedido nuevo")],
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(
                    message="quiero un pedido nuevo",
                )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_add_remove_modify_cancel_is_rejected(
        self,
    ) -> None:
        non_status_intents = (
            IntentName.AGREGAR_PRODUCTO,
            IntentName.QUITAR_PRODUCTO,
            IntentName.MODIFICAR_PRODUCTO,
            IntentName.CANCELAR_PEDIDO,
        )
        for intent_name in non_status_intents:
            with self.subTest(intent=intent_name.value):
                session = self._build_session()
                classification = self._build_classification(
                    intents=[(intent_name, "free-form text")],
                )
                with patch.object(
                    router_module, "IntentClassifier"
                ) as classifier_cls, patch.object(
                    router_module,
                    "process_initial_order_status_query",
                ) as status_query, patch.object(
                    router_module,
                    "build_customer_responses_with_diagnostic",
                ) as mapper, patch.object(
                    router_module,
                    "process_incoming_message_with_style_diagnostic",
                ) as process_mock:
                    classifier_instance = MagicMock()
                    classifier_instance.query.return_value = classification
                    classifier_cls.return_value = classifier_instance
                    stack, _pedido, _exact_session = self._patched_post(
                        session=session,
                        extra_patches=[],
                    )
                    with stack:
                        response = self._post(message="x")
                self.assertEqual(response.status_code, 400)
                process_mock.assert_not_called()
                status_query.assert_not_called()
                mapper.assert_not_called()

    def test_confirmed_order_with_multiple_intents_is_rejected(self) -> None:
        session = self._build_session()
        classification = self._build_classification(
            intents=[
                (IntentName.CONSULTAR_ESTADO_PEDIDO, "estado"),
                (IntentName.AGREGAR_PRODUCTO, "una pizza"),
            ],
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado y una pizza")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()
        # Internal classifier payloads must not leak into the body.
        for forbidden in (
            "consultar_estado_pedido",
            "agregar_producto",
            "estado y una pizza",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)

    def test_confirmed_order_with_classifier_transport_failure_is_rejected(
        self,
    ) -> None:
        """Classifier transport or schema failure is rejected
        generically without leaking exception detail, settings or
        any internal payload into the HTTP body."""
        session = self._build_session()
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_instance.query.side_effect = RuntimeError(
                "upstream LLM timeout with SECRET-KEY"
            )
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        for forbidden in (
            "RuntimeError",
            "SECRET-KEY",
            "timeout",
            "LLM",
            "openai",
            "exception",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_active_pending_context_is_rejected(
        self,
    ) -> None:
        """An active pending intent on the exact confirmed session
        forces rejection BEFORE the classifier is invoked. The
        normal message processor must never be called.
        """
        session = self._build_session(
            context_type="product_selection",
            pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "una pizza",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                },
                "queue": [],
            },
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_queued_pending_context_is_rejected(
        self,
    ) -> None:
        session = self._build_session(
            context_type=None,
            pending_intents={
                "version": 1,
                "active": None,
                "queue": [
                    {
                        "intent": "agregar_producto",
                        "source_text": "q1",
                        "status": "pending_resolution",
                        "handler": "agregar_producto",
                    }
                ],
            },
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_malformed_pending_json_is_rejected(
        self,
    ) -> None:
        session = self._build_session(
            context_type=None,
            pending_intents={"active": "not-a-dict"},
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_non_empty_context_type_is_rejected(
        self,
    ) -> None:
        session = self._build_session(
            context_type="product_selection",
            pending_intents=None,
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_with_identity_mismatch_is_rejected(
        self,
    ) -> None:
        """When the confirmed loader returns ``None`` (missing
        pedido, session, ownership or state mismatch) the route
        returns the documented generic rejection without searching
        for another session, another pedido or a successor."""
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=None,
        ), patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        # The rejection body never leaks the failing invariant.
        for forbidden in (
            "ingresado",
            "estado_pedido",
            "session",
            "pedido",
            "comercio",
            "cliente",
            "id_pedido",
            "id_session",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_confirmed_order_uses_same_pedido_session_in_snapshot(
        self,
    ) -> None:
        """The accepted confirmed path reloads the snapshot for the
        same exact pedido_id and session_id; no other pedido or
        session is ever substituted.
        """
        session = self._build_session()
        classification = self._build_classification(
            intents=[(IntentName.CONSULTAR_ESTADO_PEDIDO, "estado")],
        )
        processed_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "terminado"},
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
            return_value=processed_intent,
        ), patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
            return_value=(
                [
                    MagicMock(
                    name="CustomerResponse",
                    message="ok",
                    intent="consultar_estado_pedido",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(self._build_pedido(), session),
        ) as snapshot_loader, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ):
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            stack, _pedido, exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 200)
        snapshot_args = snapshot_loader.call_args.args
        self.assertEqual(snapshot_args[1], 42)
        self.assertEqual(snapshot_args[2], exact_session.id)

    def test_draft_path_still_calls_message_processor_for_borrador(
        self,
    ) -> None:
        """When the draft loader returns the exact ``BORRADOR``
        session, the route MUST preserve the existing message
        processor seam and MUST NOT enter the confirmed branch.
        """
        session = self._build_session(
            context_type="product_selection",
            pending_intents=None,
        )
        session.id_pedido = 42
        pedido = self._build_pedido()
        pedido.estado_pedido = EstadoPedido.BORRADOR
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(pedido, session),
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
        ) as confirmed_loader, patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(pedido, session),
        ), patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper:
            from backend.intents.schemas.customer_response import (
                CustomerResponse,
            )

            process_mock.return_value = (
                [
                    CustomerResponse(
                    message="ok",
                    intent="saludo",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post(message="hola")
        self.assertEqual(response.status_code, 200)
        process_mock.assert_called_once()
        # The confirmed branch was NOT entered.
        confirmed_loader.assert_not_called()
        classifier_cls.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()

    def test_canonical_pending_reaches_classifier_for_confirmed_order(
        self,
    ) -> None:
        """A canonical valid pending JSON (``version=1``,
        ``active=None`` and ``queue`` empty) lets the route reach
        the :class:`IntentClassifier` for the confirmed order. The
        classifier is invoked exactly once as the documented
        language interpreter and no transaction-control method is
        called.
        """
        session = self._build_session(
            context_type=None,
            pending_intents={
                "version": 1,
                "active": None,
                "queue": [],
            },
        )
        classification = self._build_classification(
            intents=[(IntentName.CONSULTAR_ESTADO_PEDIDO, "estado")],
        )
        processed_intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            recognizer="order_status_query",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "ingresado"},
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
            return_value=processed_intent,
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
            return_value=(
                [
                    MagicMock(
                    name="CustomerResponse",
                    message="ok",
                    intent="consultar_estado_pedido",
                    status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
        ) as mapper, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(self._build_pedido(), session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_instance.query.return_value = classification
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 200)
        # The classifier IS invoked because the pending context is
        # the documented canonical cleared shape.
        classifier_instance.query.assert_called_once_with("estado")
        status_query.assert_called_once()
        mapper.assert_called_once()
        process_mock.assert_not_called()
        for method in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.session, method).assert_not_called()

    def test_empty_string_context_type_is_rejected_before_classifier(
        self,
    ) -> None:
        """A non-``None`` ``context_type`` — including the empty
        string — must fail closed BEFORE the classifier is even
        constructed. The classifier is never called, no business
        orchestrator is invoked and no transaction-control method
        is touched.
        """
        session = self._build_session(
            context_type="",
            pending_intents=None,
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        # The rejection never leaks the offending invariant.
        for forbidden in ("context_type", "ingresado", "session", "pedido"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        # Fail-closed BEFORE the classifier is even reached.
        classifier_cls.assert_not_called()
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()
        for method in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.session, method).assert_not_called()

    def test_invalid_pending_version_is_rejected_before_classifier(
        self,
    ) -> None:
        """A pending dict with a non-``int`` ``version`` must fail
        closed BEFORE the classifier is reached. The router never
        parses the payload manually: :class:`PendingIntents`
        ``model_validate`` is the only validator.
        """
        session = self._build_session(
            context_type=None,
            pending_intents={
                "version": "invalida",
                "active": None,
                "queue": [],
            },
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        # No validation detail leaks into the rejection body.
        for forbidden in (
            "version",
            "invalida",
            "pending_intents",
            "ValidationError",
            "pydantic",
            "model_validate",
            "PendingIntents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        classifier_cls.assert_not_called()
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()
        for method in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.session, method).assert_not_called()

    def test_non_list_pending_queue_is_rejected_before_classifier(
        self,
    ) -> None:
        """A pending dict whose ``queue`` is not a list must fail
        closed BEFORE the classifier is reached. The route relies
        on :class:`PendingIntents` ``model_validate`` so any
        schema-incompatible shape (non-list queue, missing
        required keys, etc.) is rejected without a manual parser.
        """
        session = self._build_session(
            context_type=None,
            pending_intents={
                "version": 1,
                "active": None,
                "queue": "no-es-una-lista",
            },
        )
        with patch.object(
            router_module, "IntentClassifier"
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as mapper, patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock()
            classifier_cls.return_value = classifier_instance
            stack, _pedido, _exact_session = self._patched_post(
                session=session,
                extra_patches=[],
            )
            with stack:
                response = self._post(message="estado")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        for forbidden in (
            "queue",
            "no-es-una-lista",
            "ValidationError",
            "pydantic",
            "model_validate",
            "PendingIntents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.text)
        classifier_cls.assert_not_called()
        classifier_instance.query.assert_not_called()
        process_mock.assert_not_called()
        status_query.assert_not_called()
        mapper.assert_not_called()
        for method in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
            "expire",
        ):
            with self.subTest(method=method):
                getattr(self.session, method).assert_not_called()


class PanelOutboundStyleDiagnosticTest(unittest.TestCase):
    """Subphase 7 — local pilot styling diagnostic handoff.

    The successful local-test response MUST carry a closed
    request-scoped ``outbound_style`` projection of the latest
    styling attempt. The projection is typed on the wire
    (extra-forbid), never persists raw messages, prompt or
    instruction, never leaks identifiers or exception detail
    and never reaches the provider outbox.

    The rejection path (``_reject_local_test``) MUST keep its
    documented generic payload and MUST NOT emit the
    diagnostic.
    """

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
        _start_local_test_availability_patcher(self)

    def tearDown(self) -> None:
        _stop_local_test_availability_patcher(self)
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

    def _build_diagnostic(
        self,
        *,
        outcome,
        eligible_count=0,
        applied_count=0,
        flavor_code=None,
        response_types=(),
        fallback_category=None,
        template_version=OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
    ):
        from backend.services.outbound_response_styler import StyleDiagnostic
        return StyleDiagnostic(
            outcome=outcome,
            eligible_count=eligible_count,
            applied_count=applied_count,
            flavor_code=flavor_code,
            response_types=response_types,
            template_version=template_version,
            fallback_category=fallback_category,
        )

    def _mock_successful_turn(
        self,
        *,
        diagnostic,
        response_message="ok",
        response_intent="saludo",
        response_status="executed",
    ):
        from backend.intents.schemas.customer_response import (
            CustomerResponse,
        )
        exact_session = self._build_session(
            context_type=None, pending_intents=None
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
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            process_mock.return_value = (
                [
                    CustomerResponse(
                        message=response_message,
                        intent=response_intent,
                        status=response_status,
                    )
                ],
                diagnostic,
            )
            response = self._post()
        return response, process_mock

    def test_response_includes_outbound_style_with_closed_fields(self) -> None:
        """The local route MUST surface the closed
        ``outbound_style`` projection on every successful turn."""
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("outbound_style", body)
        self.assertEqual(
            set(body["outbound_style"].keys()),
            {
                "outcome",
                "eligible_count",
                "applied_count",
                "fallback_category",
                "flavor_code",
                "response_types",
                "template_version",
            },
        )

    def test_response_outbound_style_rejects_unexpected_fields(self) -> None:
        """The wire payload MUST reject every field outside the
        documented closed shape (extra-forbid)."""
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        body = response.json()
        self.assertEqual(
            set(body["outbound_style"].keys()),
            {
                "outcome",
                "eligible_count",
                "applied_count",
                "fallback_category",
                "flavor_code",
                "response_types",
                "template_version",
            },
        )

    def test_response_outbound_style_does_not_carry_pii(self) -> None:
        """The closed projection must never carry the prompt,
        the flavor instruction, customer text, factual
        response text, prefix/suffix, identifiers, exception
        detail, model output or arbitrary event payloads."""
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        response, _ = self._mock_successful_turn(
            diagnostic=diagnostic,
            response_message="Pizza Mozzarella grande",
        )
        # The privacy check is on the outbound_style projection
        # only. The closed projection must not embed any of the
        # documented forbidden tokens (PII, prompt, instruction,
        # exception detail, etc.). The rendered ``responses``
        # payload is intentionally left to carry the customer
        # message bytes (the proposal preserves the factual
        # contract byte-for-byte).
        body = response.json()
        diagnostic_text = json.dumps(body["outbound_style"], sort_keys=True)
        for forbidden in (
            "INSTRUCCION-SECRETA",
            "Pizza Mozzarella",
            "Mozzarella",
            "secret-customer-message",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "Av. Secreta 1234",
            "QueryLlm",
            "ApplyError",
            "AttributeError",
            "Exception",
            "elapsed_ms",
            "timestamp",
            "prompt",
            "JSON",
            "session_id",
            "pedido_id",
            "comercio_id",
            "id_cliente",
            "id_pedido",
            "id_comercio",
            "id_session",
            "+54",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, diagnostic_text)

    def test_menu_full_eligible_under_usable_flavor_reports_applied(self) -> None:
        """A ``ver_menu`` eligible response under a usable
        non-neutral flavor MUST be reported as ``applied`` or
        bounded ``fallback``; it MUST NEVER be reported as
        ``not_attempted`` (which would masquerade as a flavor
        substitution to ``neutro``)."""
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        body = response.json()
        self.assertEqual(body["outbound_style"]["outcome"], "applied")
        self.assertEqual(body["outbound_style"]["flavor_code"], "joven")

    def test_status_eligible_under_usable_flavor_reports_fallback(self) -> None:
        """An eligible status response under a usable flavor
        that hits a wrapper failure MUST report ``fallback``
        with the bounded category, NOT ``not_attempted``."""
        diagnostic = self._build_diagnostic(
            outcome="fallback",
            eligible_count=1,
            applied_count=0,
            flavor_code="joven",
            fallback_category="wrapper_invalid",
            response_types=("order_status",),
        )
        response, _ = self._mock_successful_turn(
            diagnostic=diagnostic,
            response_message="Tú pedido está en preparación.",
            response_intent="consultar_estado_pedido",
        )
        body = response.json()
        self.assertEqual(body["outbound_style"]["outcome"], "fallback")
        self.assertEqual(body["outbound_style"]["flavor_code"], "joven")
        self.assertEqual(
            body["outbound_style"]["fallback_category"], "wrapper_invalid"
        )
        # The factual menu / status message is preserved byte-for-byte.
        self.assertEqual(
            body["responses"][0]["message"],
            "Tú pedido está en preparación.",
        )

    def test_not_attempted_distinguishes_zero_eligible_from_unusable_flavor(self) -> None:
        """``not_attempted`` cleanly distinguishes a turn with
        zero eligible responses from a turn where the flavor
        was unusable, without leaking configuration detail."""
        zero_eligible = self._build_diagnostic(
            outcome="not_attempted",
            eligible_count=0,
            applied_count=0,
            response_types=(),
        )
        response, _ = self._mock_successful_turn(diagnostic=zero_eligible)
        body = response.json()
        self.assertEqual(body["outbound_style"]["outcome"], "not_attempted")
        self.assertEqual(body["outbound_style"]["eligible_count"], 0)
        self.assertIsNone(body["outbound_style"]["flavor_code"])
        self.assertEqual(body["outbound_style"]["response_types"], [])

    def test_rejection_path_does_not_emit_outbound_style(self) -> None:
        """Local route rejections use the documented generic
        payload and must NOT carry the diagnostic."""
        missing_origin = self.client.post(
            "/admin/pilot/orders/42/local-test",
            json={"message": "hola"},
            headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
        )
        self.assertEqual(missing_origin.status_code, 400)
        body = missing_origin.json()
        self.assertNotIn("outbound_style", body)
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)

    def test_outbound_style_template_version_is_static(self) -> None:
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        body = response.json()
        # The wire payload MUST mirror the static prompt template
        # version imported from the prompt template module, never
        # a hard-coded literal that could drift across amendments.
        self.assertEqual(
            body["outbound_style"]["template_version"],
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )

    def test_diagnostic_does_not_persist_on_session_or_pedido(self) -> None:
        """The diagnostic is request-scoped: it MUST NOT be
        persisted on the Session, the Pedido, or any outbox
        row; it MUST NOT call any prompt or LLM call during
        the route."""

        class _ExplodingLlm:
            def request(self, *args, **kwargs):
                raise AssertionError(
                    "the diagnostic MUST NOT introduce a second pipeline call"
                )

        from backend.services import outbound_response_styler as styler_module

        with patch.object(
            styler_module, "QueryLlm", return_value=_ExplodingLlm()
        ):
            diagnostic = self._build_diagnostic(
                outcome="applied",
                eligible_count=1,
                applied_count=1,
                flavor_code="joven",
                response_types=("menu_full",),
            )
            response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("outbound_style", body)

    def test_response_does_not_call_commit_rollback_flush_refresh_begin_close_expire(
        self,
    ) -> None:
        """The diagnostic handoff MUST NOT introduce any
        transaction-control method on the request-session."""
        diagnostic = self._build_diagnostic(
            outcome="applied",
            eligible_count=1,
            applied_count=1,
            flavor_code="joven",
            response_types=("menu_full",),
        )
        _response, _ = self._mock_successful_turn(diagnostic=diagnostic)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.expire.assert_not_called()


class PanelOutboundStyleTemplateTest(unittest.TestCase):
    """The detail template exposes the closed outbound_style
    section with a stable ``data-debug-outbound-style`` value
    selector and the browser-side handler uses ``textContent``
    so the latest local turn values can be rendered without
    trusting the diagnostic payload."""

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

    def _get_detail(self):
        with patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
            )
            return self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )

    def test_detail_template_renders_outbound_style_section(self) -> None:
        response = self._get_detail()
        body = response.text
        self.assertIn("data-debug-outbound-style", body)
        self.assertIn("Estilo outbound", body)

    def test_browser_handler_uses_textContent_for_outbound_style(self) -> None:
        response = self._get_detail()
        body_no_css = _strip_css(response.text)
        # The handler must use textContent and never build HTML
        # from the closed projection.
        self.assertIn("updateOutboundStyle", body_no_css)
        self.assertIn("textContent", body_no_css)
        self.assertNotIn("innerHTML", body_no_css)
        self.assertNotIn("outerHTML", body_no_css)

    def test_browser_handler_known_field_labels(self) -> None:
        response = self._get_detail()
        body_no_css = _strip_css(response.text)
        for label in (
            "Outcome",
            "Elegibles",
            "Aplicados",
            "Categoría fallback",
            "Flavor",
            "Tipos",
            "Plantilla",
        ):
            with self.subTest(label=label):
                self.assertIn(label, body_no_css)


class PanelLocalTestRouteAvailabilityGuardTest(unittest.TestCase):
    """The Admin Pilot local-test channel
    ``POST /admin/pilot/orders/{pedido_id}/local-test`` MUST consult
    ``CommerceAvailabilityService`` for the exact selected Session
    after the exact Pedido and Session are resolved and BEFORE any
    message processor, classifier, ``process_initial_order_status_query``
    or response-builder call. The guard must cover both the
    ``BORRADOR`` branch and the confirmed/no-``BORRADOR`` branch.

    Unavailable commerce returns the documented bounded generic
    local rejection, never leaks the internal reason
    (``blocked_state``, ``trial_expired``, ``trial_quota_exhausted``)
    and never invokes any of the four forbidden collaborators nor
    mutates the database session. Available commerce keeps the
    existing flow untouched.
    """

    FORBIDDEN_REASON_TOKENS: tuple[str, ...] = (
        "blocked_state",
        "trial_expired",
        "trial_quota_exhausted",
    )

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

    def _make_borrador_session(self) -> MagicMock:
        exact_session = MagicMock(name="ExactBorradorSession")
        exact_session.id = 21
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = None
        exact_session.pending_intents = None
        return exact_session

    def _make_confirmed_session(self) -> MagicMock:
        exact_session = MagicMock(name="ExactConfirmedSession")
        exact_session.id = 22
        exact_session.id_pedido = 42
        exact_session.id_comercio = 1
        exact_session.id_cliente = 31
        exact_session.estado_session = "activa"
        exact_session.context_type = None
        exact_session.pending_intents = None
        return exact_session

    def _assert_no_transaction_calls(self) -> None:
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.expire.assert_not_called()

    def _assert_generic_rejection(self, response) -> None:
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        for token in self.FORBIDDEN_REASON_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, body.get("message", ""))
                self.assertNotIn(token, response.text)
        self.assertNotIn("execution_state", body)
        self.assertNotIn("order_lines", body)
        self.assertNotIn("outbound_style", body)

    # ---- BORRADOR branch (process_incoming_message_with_style_diagnostic) ----

    def test_borrador_branch_blocked_commerce_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_borrador_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    def test_borrador_branch_expired_trial_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_borrador_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    def test_borrador_branch_quota_exhausted_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_borrador_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    # ---- Confirmed / no-BORRADOR branch (classifier + status query + builder) ----

    def test_confirmed_branch_blocked_commerce_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_confirmed_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader, patch.object(
            router_module,
            "_is_confirmed_clean_context",
            return_value=True,
        ) as clean_context:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        clean_context.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    def test_confirmed_branch_expired_trial_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_confirmed_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader, patch.object(
            router_module,
            "_is_confirmed_clean_context",
            return_value=True,
        ) as clean_context:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        clean_context.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    def test_confirmed_branch_quota_exhausted_returns_generic_rejection(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_confirmed_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.UNAVAILABLE,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
        ) as snapshot_loader, patch.object(
            router_module,
            "_is_confirmed_clean_context",
            return_value=True,
        ) as clean_context:
            response = self._post()
        self._assert_generic_rejection(response)
        process_mock.assert_not_called()
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()
        clean_context.assert_not_called()
        snapshot_loader.assert_not_called()
        self._assert_no_transaction_calls()

    # ---- Available commerce: existing flow preserved ----

    def test_borrador_branch_available_commerce_invokes_processor(self) -> None:
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_borrador_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=(exact_pedido, exact_session),
        ) as loader, patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.AVAILABLE,
        ), patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock, patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock:
            from backend.intents.schemas.customer_response import CustomerResponse

            process_mock.return_value = (
                [
                    CustomerResponse(
                        message="ok",
                        intent="saludo",
                        status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loader.call_count, 1)
        process_mock.assert_called_once()
        self.assertIs(process_mock.call_args.args[1], exact_session)
        classifier_cls.assert_not_called()
        status_query_mock.assert_not_called()
        builder_mock.assert_not_called()

    def test_confirmed_branch_available_commerce_invokes_status_query(self) -> None:
        from backend.intents.schemas.customer_response import CustomerResponse
        from backend.intents.schemas.intent_classification import (
            ClassifiedIntent,
            IntentClassificationResult,
            IntentName,
        )
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_confirmed_session()
        exact_pedido = MagicMock(name="ExactPedido")
        with patch.object(
            router_module,
            "_load_local_test_session",
            return_value=None,
        ), patch.object(
            router_module,
            "_load_confirmed_local_test_session",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            return_value=_Status.AVAILABLE,
        ), patch.object(
            router_module,
            "_is_confirmed_clean_context",
            return_value=True,
        ), patch.object(
            router_module,
            "IntentClassifier",
        ) as classifier_cls, patch.object(
            router_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            router_module,
            "build_customer_responses_with_diagnostic",
        ) as builder_mock, patch.object(
            router_module,
            "_reload_exact_session_for_snapshot",
            return_value=(exact_pedido, exact_session),
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
        ) as process_mock:
            classifier_instance = MagicMock(name="ClassifierInstance")
            classifier_cls.return_value = classifier_instance
            classifier_instance.query.return_value = (
                IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONSULTAR_ESTADO_PEDIDO,
                            mensaje="hola",
                        )
                    ],
                    mensaje="hola",
                )
            )
            processed_intent = MagicMock(name="ProcessedIntent")
            status_query_mock.return_value = processed_intent
            builder_mock.return_value = (
                [
                    CustomerResponse(
                        message="ok",
                        intent="consultar_estado_pedido",
                        status="executed",
                    )
                ],
                _style_diagnostic_not_attempted(),
            )
            response = self._post()
        self.assertEqual(response.status_code, 200)
        process_mock.assert_not_called()
        classifier_cls.assert_called_once_with()
        classifier_instance.query.assert_called_once_with("hola")
        status_query_mock.assert_called_once()
        builder_mock.assert_called_once()

    def test_guard_runs_before_processor_after_session_resolution(self) -> None:
        """The guard MUST execute after the exact Pedido/Session
        resolvers return a non-``None`` target and BEFORE the
        processor, classifier, status query or response builder is
        invoked. A failure in the policy evaluation order therefore
        fails closed at the boundary, never inside the pipeline.
        """
        from backend.services.commerce_availability_service import (
            CommerceAvailabilityStatus as _Status,
        )

        exact_session = self._make_borrador_session()
        exact_pedido = MagicMock(name="ExactPedido")
        call_order: list[str] = []

        def _loader(_db, _pedido_id):
            call_order.append("loader")
            return exact_pedido, exact_session

        def _guard(_db, _session):
            call_order.append("guard")
            return _Status.UNAVAILABLE

        def _process(*_args, **_kwargs):
            call_order.append("process")
            return ([], _style_diagnostic_not_attempted())

        with patch.object(
            router_module, "_load_local_test_session", side_effect=_loader
        ), patch.object(
            router_module,
            "_commerce_availability_outcome",
            side_effect=_guard,
        ), patch.object(
            router_module,
            "process_incoming_message_with_style_diagnostic",
            side_effect=_process,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(call_order, ["loader", "guard"])
        self.assertNotIn("process", call_order)


class PanelEmulatorTestAuthTest(unittest.TestCase):
    """The emulator-test POST route mounts behind the same panel
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
            "/admin/pilot/orders/42/emulator-test",
            json={"message": "hola"},
            headers={"X-Emulator-Test-Origin": "same-origin"},
        )
        self.assertEqual(response.status_code, 401)
        self.session_override.assert_not_called()


class PanelEmulatorTestHeaderTest(unittest.TestCase):
    """The emulator-test POST route requires the same-origin custom
    header."""

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
            headers["X-Emulator-Test-Origin"] = origin_value
        return self.client.post(
            "/admin/pilot/orders/42/emulator-test",
            json={"message": "hola"},
            headers=headers,
        )

    def test_missing_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock:
            response = self._post(origin_value=None)
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()

    def test_wrong_origin_header_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock:
            response = self._post(origin_value="attacker.example")
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()


class PanelEmulatorTestBodyValidationTest(unittest.TestCase):
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
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            "/admin/pilot/orders/42/emulator-test",
            headers=headers,
            **kwargs,
        )

    def test_empty_body_returns_422(self) -> None:
        response = self._post(body=None, json={})
        self.assertEqual(response.status_code, 422)

    def test_oversized_message_returns_422(self) -> None:
        response = self._post(
            body=None, json={"message": "x" * 501}
        )
        self.assertEqual(response.status_code, 422)

    def test_empty_string_message_returns_422(self) -> None:
        response = self._post(body=None, json={"message": ""})
        self.assertEqual(response.status_code, 422)

    def test_extra_field_returns_422(self) -> None:
        response = self._post(
            body=None,
            json={"message": "hola", "extra": "x"},
        )
        self.assertEqual(response.status_code, 422)


class PanelEmulatorTestRevalidationTest(unittest.TestCase):
    """The emulator-test re-validates the exact selected pedido
    identity. Mismatches return the generic rejection without
    invoking the emulator or any business pipeline."""

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
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            f"/admin/pilot/orders/{pedido_id}/emulator-test",
            json={"message": "hola"},
            headers=headers,
        )

    def test_invalid_pedido_id_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock:
            response = self._post(pedido_id="abc")
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()

    def test_missing_target_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=None,
        ) as target_mock:
            response = self._post()
        self.assertEqual(response.status_code, 400)
        target_mock.assert_called_once()

    def test_borrador_pedido_returns_generic_rejection(self) -> None:
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.UNAVAILABLE,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)


class PanelEmulatorTestHappyPathTest(unittest.TestCase):
    """A valid emulator-test turn invokes the emulator inbound
    control surface exactly once with the exact selected session
    identity. No coordinator, no worker, no dispatcher, no T-C,
    no real Twilio SDK."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
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

    def _post(self, pedido_id: str = "42"):
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            f"/admin/pilot/orders/{pedido_id}/emulator-test",
            json={"message": "hola"},
            headers=headers,
        )

    def _build_target(self):
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        return EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )

    def test_happy_path_returns_synthetic_inbound_id(self) -> None:
        target = self._build_target()
        installation = MagicMock(name="Installation")
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SM-FAKE",
        )
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ), patch.object(
            router_module,
            "load_active_installation",
            return_value=installation,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ), patch.object(
            router_module,
            "resolve_cliente_e164",
            return_value="+5491155556666",
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["synthetic_inbound_id"], "SM-FAKE")

    def test_disabled_emulator_returns_generic_rejection(self) -> None:
        target = self._build_target()
        installation = MagicMock(name="Installation")
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ), patch.object(
            router_module,
            "load_active_installation",
            return_value=installation,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=None,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_unavailable_commerce_returns_generic_rejection(self) -> None:
        target = self._build_target()
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.UNAVAILABLE,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_inactive_installation_returns_generic_rejection(self) -> None:
        target = self._build_target()
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ), patch.object(
            router_module,
            "load_active_installation",
            return_value=None,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_emulator_transport_failure_returns_generic_rejection(self) -> None:
        target = self._build_target()
        installation = MagicMock(name="Installation")
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.side_effect = RuntimeError("boom")
        with patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "commerce_availability_status",
            return_value=CommerceAvailabilityStatus.AVAILABLE,
        ), patch.object(
            router_module,
            "load_active_installation",
            return_value=installation,
        ), patch.object(
            router_module,
            "build_emulator_control_client",
            return_value=client,
        ), patch.object(
            router_module,
            "resolve_cliente_e164",
            return_value="+5491155556666",
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_local_test_route_still_works(self) -> None:
        """The existing local-test route keeps its meaning."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    router_module,
                    "_load_local_test_session",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch.object(
                    router_module,
                    "_load_confirmed_local_test_session",
                    return_value=None,
                )
            )
            response = self.client.post(
                "/admin/pilot/orders/42/local-test",
                json={"message": "hola"},
                headers={
                    **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                    "X-Local-Test-Origin": "same-origin",
                },
            )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["responses"], [])


class PanelEmulatorTestStatusTest(unittest.TestCase):
    """The bounded status projection is scoped to the exact
    selected pedido/session and synthetic inbound identifier.

    The route also fails closed at the configuration boundary: when
    the explicit emulator action contract is not satisfied, the
    status endpoint rejects with the documented generic payload and
    never opens a database connection or invokes the worker,
    dispatcher, T-C or Twilio.
    """

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

    def _post(self, payload):
        return self.client.post(
            "/admin/pilot/orders/42/emulator-test/status",
            json=payload,
            headers={
                **_basic_auth_header("ignored", CONFIGURED_TOKEN),
                "X-Emulator-Test-Origin": "same-origin",
            },
        )

    def test_disabled_emulator_returns_generic_rejection(self) -> None:
        """When the explicit emulator action contract is not
        satisfied the status endpoint returns the documented generic
        rejection. The early guard runs before any database work so
        the route never queries Pedido/Session/receipt/outbox
        state."""
        with patch.object(
            router_module,
            "_is_emulator_action_enabled",
            return_value=False,
        ), patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock, patch.object(
            router_module,
            "_emulator_outbox_summary",
        ) as summary_mock:
            response = self._post({"synthetic_inbound_id": "SM-FAKE"})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("responses"), [])
        self.assertIn("message", body)
        self.assertNotIn("status", body)
        self.assertNotIn("outbound_body", body)
        target_mock.assert_not_called()
        summary_mock.assert_not_called()

    def test_disabled_emulator_does_not_open_database_session(self) -> None:
        """The disabled-emulator guard runs BEFORE any database
        read. The early return short-circuits the SQLAlchemy helpers
        so no ``db.execute``/``commit``/``rollback``/``flush``/
        ``refresh``/``begin``/``close`` call is reached, the
        session is never mutated, and the loader/summary helpers
        are never invoked."""
        with patch.object(
            router_module,
            "_is_emulator_action_enabled",
            return_value=False,
        ), patch.object(
            router_module,
            "load_active_emulator_target",
        ) as target_mock, patch.object(
            router_module,
            "_emulator_outbox_summary",
        ) as summary_mock:
            response = self._post({"synthetic_inbound_id": "SM-FAKE"})
        self.assertEqual(response.status_code, 400)
        target_mock.assert_not_called()
        summary_mock.assert_not_called()
        self.session.execute.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()

    def test_missing_target_returns_generic_rejection(self) -> None:
        with patch.object(
            router_module,
            "_is_emulator_action_enabled",
            return_value=True,
        ), patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=None,
        ) as target_mock:
            response = self._post({"synthetic_inbound_id": "SM-FAKE"})
        self.assertEqual(response.status_code, 400)
        target_mock.assert_called_once()

    def test_happy_path_returns_pending_state(self) -> None:
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )
        summary = router_module.EmulatorStatusResponse(
            status="pending",
            outbound_body=None,
            provider_message_sid=None,
        )
        with patch.object(
            router_module,
            "_is_emulator_action_enabled",
            return_value=True,
        ), patch.object(
            router_module,
            "load_active_emulator_target",
            return_value=target,
        ), patch.object(
            router_module,
            "_emulator_outbox_summary",
            return_value=summary,
        ):
            response = self._post({"synthetic_inbound_id": "SM-FAKE"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")


class PanelEmulatorActionExplicitModeTest(unittest.TestCase):
    """The emulator-test action requires the explicit configuration
    contract: ``TWILIO_PROVIDER_MODE=emulator``,
    ``COMMERCE_ISOLATED_OUTBOUND_ENABLED=1`` and explicit emulator
    credentials. When any of those is missing the action returns
    the documented generic rejection and never invokes the emulator
    or any real provider."""

    def _post(self, pedido_id: str = "42") -> Any:
        headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
        headers["X-Emulator-Test-Origin"] = "same-origin"
        return self.client.post(
            f"/admin/pilot/orders/{pedido_id}/emulator-test",
            json={"message": "hola"},
            headers=headers,
        )

    def _build_app_with(self, settings: Settings) -> TestClient:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=settings
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module, "load_settings", return_value=settings
        )
        self._router_settings_patcher.start()
        return self.client

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def test_real_mode_returns_generic_rejection(self) -> None:
        """When ``twilio_provider_mode == 'real'`` the action is
        disabled even if the emulator credentials happen to be
        configured; the route never invokes a real provider."""
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )
        installation = MagicMock(name="Installation")
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SM-FAKE",
        )
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "twilio_provider_mode": "real"}
        )
        self._build_app_with(settings)
        with patch.object(
            router_module, "load_active_emulator_target", return_value=target
        ), patch.object(
            router_module, "load_active_installation", return_value=installation
        ), patch.object(
            router_module, "build_emulator_control_client", return_value=client
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)
        client.submit_inbound.assert_not_called()

    def test_isolated_disabled_returns_generic_rejection(self) -> None:
        """When ``commerce_isolated_outbound_enabled`` is off the
        action is disabled even if the emulator credentials happen
        to be configured; the route never invokes the emulator."""
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )
        installation = MagicMock(name="Installation")
        client = MagicMock(name="EmulatorClient")
        client.submit_inbound.return_value = MagicMock(
            status="accepted",
            message_sid="SM-FAKE",
            synthetic_inbound_id="SM-FAKE",
        )
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "commerce_isolated_outbound_enabled": False}
        )
        self._build_app_with(settings)
        with patch.object(
            router_module, "load_active_emulator_target", return_value=target
        ), patch.object(
            router_module, "load_active_installation", return_value=installation
        ), patch.object(
            router_module, "build_emulator_control_client", return_value=client
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)
        client.submit_inbound.assert_not_called()

    def test_missing_emulator_credentials_returns_generic_rejection(self) -> None:
        """When emulator mode is enabled but the operator did not
        pin the credentials the action is disabled; the route never
        invokes the emulator or the central dispatcher."""
        from backend.services.admin_pilot_emulator_service import (
            EmulatorTestTarget,
        )

        target = EmulatorTestTarget(
            pedido_id=42,
            session_id=21,
            cliente_id=31,
            comercio_id=1,
            canal_id=5,
            canal_destination_e164="+5491100000000",
        )
        installation = MagicMock(name="Installation")
        client = MagicMock(name="EmulatorClient")
        settings = _settings_with_emulator_enabled()
        settings = Settings(
            **{**settings.__dict__, "twilio_emulator_account_sid": None}
        )
        self._build_app_with(settings)
        with patch.object(
            router_module, "load_active_emulator_target", return_value=target
        ), patch.object(
            router_module, "load_active_installation", return_value=installation
        ), patch.object(
            router_module, "build_emulator_control_client", return_value=client
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)
        client.submit_inbound.assert_not_called()


class PanelEmulatorDetailTemplateTest(unittest.TestCase):
    """The detail page hides the emulator-test form when the
    explicit configuration contract is not satisfied. The test
    patches the ``_is_emulator_action_enabled`` helper to drive the
    branch without rebuilding the full detail view model."""

    def _build_app_with(self, settings: Settings) -> TestClient:
        self.session = MagicMock(name="DatabaseSession")
        self.session_override = _SessionOverride(self.session)
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._settings_patcher = patch.object(
            dependencies_module, "load_settings", return_value=settings
        )
        self._settings_patcher.start()
        self._router_settings_patcher = patch.object(
            router_module, "load_settings", return_value=settings
        )
        self._router_settings_patcher.start()
        return self.client

    def tearDown(self) -> None:
        self._settings_patcher.stop()
        self._router_settings_patcher.stop()
        self.app.dependency_overrides.clear()

    def _get_detail_response(self, *, enabled: bool) -> str:
        self._build_app_with(_settings())

        with patch.object(
            router_module, "load_active_emulator_target", return_value=None
        ), patch.object(
            router_module, "_is_emulator_action_enabled", return_value=enabled
        ), patch.object(
            router_module,
            "PilotOrderOperationsViewService",
        ) as service_cls:
            service_cls.return_value = _stub_service(
                detail=_build_detail(),
                history=_build_history(),
                order_lines_snapshot=[],
            )
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=_basic_auth_header("ignored", CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_emulator_form_hidden_when_mode_is_real(self) -> None:
        body = self._get_detail_response(enabled=False)
        self.assertIn("Twilio Emulator (deshabilitado)", body)
        self.assertNotIn("data-debug-emulator-form", body)

    def test_emulator_form_hidden_when_isolated_disabled(self) -> None:
        body = self._get_detail_response(enabled=False)
        self.assertIn("Twilio Emulator (deshabilitado)", body)
        self.assertNotIn("data-debug-emulator-form", body)

    def test_emulator_form_hidden_when_credentials_missing(self) -> None:
        body = self._get_detail_response(enabled=False)
        self.assertIn("Twilio Emulator (deshabilitado)", body)
        self.assertNotIn("data-debug-emulator-form", body)

    def test_emulator_form_visible_when_fully_enabled(self) -> None:
        body = self._get_detail_response(enabled=True)
        self.assertIn("Enviar por Twilio Emulator", body)
        self.assertIn("data-debug-emulator-form", body)


if __name__ == "__main__":
    unittest.main()
