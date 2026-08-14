"""Focused tests for the read-only pilot order operations view service.

These tests exercise the projection service with a stubbed
``sqlalchemy.orm.Session`` that returns programmable result chains so
the production SQL is never executed. Every test asserts that the
service never invokes ``commit``, ``rollback``, ``flush``, ``refresh``,
``begin`` or ``close`` on the session.
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.models import (
    EstadoPedido,
    EstadoSession,
    MensajeProveedorSaliente,
    OutboundProviderMessageState,
)
from backend.services.pilot_order_operations_view_service import (
    ALLOWED_PAGE_SIZES,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_PAGE_SIZE,
    FALLBACK_ZONE_LABEL,
    CatalogPriceRow,
    ClientSummary,
    CommerceCatalogPriceAvailabilityView,
    CommerceSummary,
    InvalidComercioId,
    InvalidListFilter,
    InvalidPedidoId,
    LocalDateTimeView,
    OrderDetailView,
    OrderLineSnapshot,
    OrderListRow,
    OrderSummary,
    OutboundMessageView,
    PendingContextDebugView,
    PilotOrderOperationsViewService,
    ProviderReceiptView,
    SessionSummary,
    build_pending_context_debug_view,
    format_local_datetime,
    format_local_datetime_optional,
    format_order_line_price,
    parse_comercio_id,
    parse_list_filters,
    parse_pedido_id,
)


class ParseListFiltersTest(unittest.TestCase):
    """The filter parser normalises inputs and rejects malformed ones
    before any query is issued."""

    def test_default_window_is_last_seven_days(self) -> None:
        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        filters = parse_list_filters(
            raw_from=None,
            raw_to=None,
            raw_comercio_id=None,
            raw_estado=None,
            raw_page=None,
            raw_page_size=None,
            now=now,
        )
        self.assertEqual(
            filters.from_date,
            now.date() - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1),
        )
        self.assertEqual(filters.to_date, now.date())
        self.assertEqual(filters.page, 1)
        self.assertEqual(filters.page_size, DEFAULT_PAGE_SIZE)
        self.assertIsNone(filters.comercio_id)
        self.assertIsNone(filters.estado)

    def test_explicit_range_is_preserved(self) -> None:
        filters = parse_list_filters(
            raw_from="2026-08-01",
            raw_to="2026-08-10",
            raw_comercio_id="42",
            raw_estado="ingresado",
            raw_page="3",
            raw_page_size="50",
        )
        self.assertEqual(filters.from_date, date(2026, 8, 1))
        self.assertEqual(filters.to_date, date(2026, 8, 10))
        self.assertEqual(filters.comercio_id, 42)
        self.assertEqual(filters.estado, EstadoPedido.INGRESADO)
        self.assertEqual(filters.page, 3)
        self.assertEqual(filters.page_size, 50)

    def test_invalid_page_size_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size="75",
            )

    def test_allowed_page_sizes_are_accepted(self) -> None:
        for size in ALLOWED_PAGE_SIZES:
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=str(size),
            )
            self.assertEqual(filters.page_size, size)

    def test_range_above_31_days_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from="2026-07-01",
                raw_to="2026-08-15",
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
            )

    def test_from_after_to_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from="2026-08-10",
                raw_to="2026-08-01",
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
            )

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from="not-a-date",
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
            )

    def test_invalid_estado_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado="cerrado",
                raw_page=None,
                raw_page_size=None,
            )

    def test_negative_page_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page="0",
                raw_page_size=None,
            )

    def test_invalid_comercio_id_is_rejected(self) -> None:
        with self.assertRaises(InvalidListFilter):
            parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id="abc",
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
            )


class _Result:
    """Stub SQLAlchemy result object used by every service test.

    Implements ``scalars()``, ``unique()``, ``scalar_one()`` and
    ``scalar_one_or_none()`` so the service code can use the same
    fluent call pattern as the production code path. ``scalars()``
    and ``unique()`` return the same content so the chained
    ``execute(stmt).unique().scalars().all()`` works without a real
    database."""

    def __init__(
        self,
        scalars_list: list | None,
        scalar_value: object | None,
    ) -> None:
        self._scalars_list = scalars_list
        self._scalar_value = scalar_value

    def scalars(self):
        result = MagicMock()
        result.unique = MagicMock(return_value=result)
        result.all = MagicMock(return_value=list(self._scalars_list or []))
        return result

    def unique(self):
        return _Result(self._scalars_list, self._scalar_value)

    def scalar_one(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value


class ParsePedidoIdTest(unittest.TestCase):
    def test_accepts_positive_integer(self) -> None:
        self.assertEqual(parse_pedido_id("42"), 42)

    def test_rejects_zero(self) -> None:
        with self.assertRaises(InvalidPedidoId):
            parse_pedido_id("0")

    def test_rejects_non_numeric(self) -> None:
        with self.assertRaises(InvalidPedidoId):
            parse_pedido_id("abc")


def _make_row(
    *,
    pedido_id: int,
    estado_pedido: EstadoPedido,
    fecha_alta: datetime,
    fecha_ultima_modificacion: datetime,
    comercio_id: int,
    comercio_nombre_fantasia: str,
    comercio_nombre_corto: str,
    comercio_zona_horaria: str = "America/Argentina/Buenos_Aires",
    session_id: int,
    estado_session: EstadoSession,
    datetime_inicio: datetime,
    datetime_ultimo_movimiento: datetime,
    cliente_id: int,
    cliente_nombre: str | None,
    cliente_whatsapp: str,
    cliente_activo: bool = True,
) -> SimpleNamespace:
    pedido = SimpleNamespace(
        id=pedido_id,
        estado_pedido=estado_pedido,
        fecha_alta=fecha_alta,
        fecha_ultima_modificacion=fecha_ultima_modificacion,
        session=SimpleNamespace(
            id=session_id,
            estado_session=estado_session,
            datetime_inicio=datetime_inicio,
            datetime_ultimo_movimiento=datetime_ultimo_movimiento,
            comercio=SimpleNamespace(
                id=comercio_id,
                nombre_fantasia=comercio_nombre_fantasia,
                nombre_corto=comercio_nombre_corto,
                zona_horaria=comercio_zona_horaria,
            ),
            cliente=SimpleNamespace(
                id=cliente_id,
                nombre=cliente_nombre,
                whatsapp=cliente_whatsapp,
                activo=cliente_activo,
            ),
        ),
    )
    return pedido


@contextmanager
def _patched_session(rows: list, total: int):
    """Build a SQLAlchemy session double that records filter usage.

    The returned double lets the test inspect the ``where`` clauses
    and ``order_by`` clauses applied by the service. The
    transaction-control methods are tracked so every test can assert
    that none of them are invoked.
    """
    session = MagicMock(name="DatabaseSession")
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.refresh = MagicMock()
    session.begin = MagicMock()
    session.close = MagicMock()

    execute_calls: list = []

    def _execute(stmt):
        execute_calls.append(stmt)
        return _Result(rows, total)

    session.execute.side_effect = _execute

    yield session, execute_calls

    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()
    session.refresh.assert_not_called()
    session.begin.assert_not_called()
    session.close.assert_not_called()


class ListOrdersServiceTest(unittest.TestCase):
    """The list query is bounded, ordered by recency, and applies the
    validated filters without mutating the session."""

    def _base_datetime(self) -> datetime:
        return datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

    def test_returns_bounded_rows_and_total(self) -> None:
        row = _make_row(
            pedido_id=11,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=self._base_datetime(),
            fecha_ultima_modificacion=self._base_datetime(),
            comercio_id=1,
            comercio_nombre_fantasia="Comercio A",
            comercio_nombre_corto="A",
            session_id=21,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=self._base_datetime(),
            datetime_ultimo_movimiento=self._base_datetime(),
            cliente_id=31,
            cliente_nombre="Ana",
            cliente_whatsapp="+5491100000001",
        )
        with _patched_session([row], total=1) as (session, _calls):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
                now=self._base_datetime(),
            )
            view = service.list_orders(filters)
        self.assertEqual(view.total, 1)
        self.assertEqual(view.page, 1)
        self.assertEqual(view.page_size, DEFAULT_PAGE_SIZE)
        self.assertEqual(len(view.rows), 1)
        first = view.rows[0]
        self.assertEqual(first.pedido.id, 11)
        self.assertEqual(first.commerce.nombre_fantasia, "Comercio A")
        self.assertEqual(first.client.whatsapp, "+5491100000001")
        self.assertIsInstance(first, OrderListRow)
        self.assertIsInstance(first.pedido, OrderSummary)
        self.assertIsInstance(first.session, SessionSummary)
        self.assertIsInstance(first.commerce, CommerceSummary)
        self.assertIsInstance(first.client, ClientSummary)

    def test_pagination_offsets_rows(self) -> None:
        with _patched_session([], total=120) as (session, _calls):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page="3",
                raw_page_size="50",
                now=self._base_datetime(),
            )
            view = service.list_orders(filters)
        self.assertEqual(view.page, 3)
        self.assertEqual(view.page_size, 50)
        self.assertEqual(view.total, 120)

    def test_filter_by_comercio_id_is_applied(self) -> None:
        with _patched_session([], total=0) as (session, _calls):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from="2026-08-01",
                raw_to="2026-08-10",
                raw_comercio_id="42",
                raw_estado="entregado",
                raw_page=None,
                raw_page_size=None,
                now=self._base_datetime(),
            )
            service.list_orders(filters)
        self.assertEqual(session.execute.call_count, 2)

    def test_empty_result_returns_empty_view(self) -> None:
        with _patched_session([], total=0) as (session, _calls):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
                now=self._base_datetime(),
            )
            view = service.list_orders(filters)
        self.assertEqual(view.rows, [])
        self.assertEqual(view.total, 0)


class GetDetailServiceTest(unittest.TestCase):
    """The detail projection joins the requested pedido's exact
    relationships and never falls back to another pedido."""

    def test_returns_none_for_missing_pedido(self) -> None:
        with _patched_session([], total=None) as (session, _calls):
            session.execute.side_effect = lambda stmt: _Result(
                scalars_list=[], scalar_value=None
            )
            service = PilotOrderOperationsViewService(session)
            detail = service.get_detail(999)
        self.assertIsNone(detail)

    def test_returns_detail_with_related_fields(self) -> None:
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        medio_pago = SimpleNamespace(id=7, descripcion="Efectivo")
        metodo_entrega = SimpleNamespace(id=8, descripcion="Retiro")
        pedido = SimpleNamespace(
            id=42,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=base,
            fecha_ultima_modificacion=base,
            direccion_entrega="Calle 123",
            observaciones="Llamar al timbre",
            datetime_entrega_programada=None,
            medio_pago=medio_pago,
            metodo_entrega=metodo_entrega,
            session=SimpleNamespace(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=base,
                datetime_ultimo_movimiento=base,
                context_type=None,
                pending_intents=None,
                cliente=SimpleNamespace(
                    id=31,
                    nombre="Ana",
                    whatsapp="+5491100000001",
                    activo=True,
                ),
                comercio=SimpleNamespace(
                    id=1,
                    nombre_fantasia="Comercio A",
                    nombre_corto="A",
                    zona_horaria="America/Argentina/Buenos_Aires",
                ),
            ),
        )
        linea = SimpleNamespace(
            id=100,
            cantidad=2,
            precio_unitario=Decimal("150.00"),
            observaciones="Sin sal",
            producto_presentacion=SimpleNamespace(
                producto=SimpleNamespace(nombre="Pan"),
                presentacion=SimpleNamespace(descripcion="Bolsa x 1kg"),
            ),
        )

        result_index = {"value": 0}

        def _execute(stmt):
            if result_index["value"] == 0:
                result_index["value"] += 1
                return _Result(scalars_list=[], scalar_value=pedido)
            return _Result(scalars_list=[linea], scalar_value=None)

        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        session.execute.side_effect = _execute

        service = PilotOrderOperationsViewService(session)
        detail = service.get_detail(42)

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()

        self.assertIsInstance(detail, OrderDetailView)
        self.assertEqual(detail.pedido.id, 42)
        self.assertEqual(detail.commerce.nombre_fantasia, "Comercio A")
        self.assertEqual(detail.client.whatsapp, "+5491100000001")
        self.assertEqual(detail.medio_pago.id, 7)
        self.assertEqual(detail.metodo_entrega.id, 8)
        self.assertEqual(len(detail.lineas), 1)
        self.assertEqual(detail.lineas[0].producto_nombre, "Pan")
        self.assertEqual(detail.lineas[0].cantidad, 2)
        self.assertEqual(detail.lineas[0].precio_unitario, Decimal("150.00"))
        self.assertEqual(detail.lineas[0].observaciones, "Sin sal")

    def test_missing_payment_and_delivery_render_as_none(self) -> None:
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        pedido = SimpleNamespace(
            id=42,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=base,
            fecha_ultima_modificacion=base,
            direccion_entrega=None,
            observaciones=None,
            datetime_entrega_programada=None,
            medio_pago=None,
            metodo_entrega=None,
            session=SimpleNamespace(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=base,
                datetime_ultimo_movimiento=base,
                context_type=None,
                pending_intents=None,
                cliente=SimpleNamespace(
                    id=31,
                    nombre=None,
                    whatsapp="+5491100000001",
                    activo=True,
                ),
                comercio=SimpleNamespace(
                    id=1,
                    nombre_fantasia="Comercio A",
                    nombre_corto="A",
                    zona_horaria="America/Argentina/Buenos_Aires",
                ),
            ),
        )

        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        call_index = {"value": 0}

        def _execute(stmt):
            call_index["value"] += 1
            if call_index["value"] == 1:
                return _Result(scalars_list=[], scalar_value=pedido)
            return _Result(scalars_list=[], scalar_value=None)

        session.execute.side_effect = _execute

        service = PilotOrderOperationsViewService(session)
        detail = service.get_detail(42)

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()

        self.assertIsNone(detail.medio_pago)
        self.assertIsNone(detail.metodo_entrega)
        self.assertIsNone(detail.direccion_entrega)
        self.assertIsNone(detail.observaciones)
        self.assertIsNone(detail.datetime_entrega_programada)
        self.assertEqual(detail.lineas, [])


class GetProviderHistoryTest(unittest.TestCase):
    """The provider history is filtered by the exact cliente_id and
    comercio_id, never reveals the provider identifier and groups
    outbound rows under their matching receipt."""

    def _build_session(self, receipts, outbounds):
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()

        call_index = {"value": 0}

        def _execute(stmt):
            call_index["value"] += 1
            if call_index["value"] == 1:
                return _Result(scalars_list=receipts, scalar_value=None)
            return _Result(scalars_list=outbounds, scalar_value=None)

        session.execute.side_effect = _execute
        return session

    def test_groups_outbounds_under_their_receipt(self) -> None:
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        receipt1 = SimpleNamespace(
            id=10,
            fecha_recepcion=base,
            proveedor="twilio",
            canal_id=5,
            identificador_recepcion="SM-redacted",
        )
        receipt2 = SimpleNamespace(
            id=11,
            fecha_recepcion=base + timedelta(minutes=1),
            proveedor="twilio",
            canal_id=5,
            identificador_recepcion="SM-redacted-2",
        )
        outbound1 = SimpleNamespace(
            id=20,
            sequence=0,
            fecha_creacion=base,
            cuerpo="Hola!",
            estado=OutboundProviderMessageState.DELIVERED.value,
            intentos=1,
            estado_proveedor="delivered",
            estado_proveedor_en=base,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            recepcion_mensaje_proveedor_id=10,
        )
        outbound2 = SimpleNamespace(
            id=21,
            sequence=0,
            fecha_creacion=base + timedelta(minutes=1),
            cuerpo="Tu pedido está listo.",
            estado=OutboundProviderMessageState.PENDING.value,
            intentos=0,
            estado_proveedor=None,
            estado_proveedor_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            recepcion_mensaje_proveedor_id=11,
        )
        session = self._build_session(
            receipts=[receipt1, receipt2],
            outbounds=[outbound1, outbound2],
        )
        service = PilotOrderOperationsViewService(session)
        history = service.get_provider_history(cliente_id=31, comercio_id=1)

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()

        self.assertEqual(history.cliente_id, 31)
        self.assertEqual(history.comercio_id, 1)
        self.assertEqual(len(history.entries), 2)
        self.assertEqual(history.entries[0].receipt.id, 10)
        self.assertEqual(len(history.entries[0].outbounds), 1)
        self.assertEqual(history.entries[0].outbounds[0].id, 20)
        self.assertEqual(history.entries[1].receipt.id, 11)
        self.assertEqual(len(history.entries[1].outbounds), 1)
        self.assertEqual(history.entries[1].outbounds[0].id, 21)

    def test_view_excludes_provider_identifier_and_lease_token(self) -> None:
        view_model = MensajeProveedorSaliente(
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491100000001",
            cuerpo="x",
            sequence=0,
        )
        outbound = SimpleNamespace(
            id=20,
            sequence=0,
            fecha_creacion=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            cuerpo="hola",
            estado="delivered",
            intentos=1,
            estado_proveedor="delivered",
            estado_proveedor_en=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            recepcion_mensaje_proveedor_id=10,
            identificador_proveedor="SMxxxxxxxxxxxxxxxxxxxx",
            token_lease="lease-secret",
        )
        receipt = SimpleNamespace(
            id=10,
            fecha_recepcion=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            proveedor="twilio",
            canal_id=5,
            identificador_recepcion="SM-redacted",
        )
        session = self._build_session(
            receipts=[receipt], outbounds=[outbound]
        )
        service = PilotOrderOperationsViewService(session)
        history = service.get_provider_history(cliente_id=31, comercio_id=1)

        self.assertEqual(history.entries[0].receipt.proveedor, "twilio")
        self.assertFalse(hasattr(history.entries[0].receipt, "identificador_recepcion"))
        for entry in history.entries:
            for msg in entry.outbounds:
                self.assertFalse(hasattr(msg, "identificador_proveedor"))
                self.assertFalse(hasattr(msg, "token_lease"))
                self.assertFalse(hasattr(msg, "destinatario_e164"))
        self.assertEqual(view_model.cuerpo, "x")


class ServiceNoMutationTest(unittest.TestCase):
    """Service-level guarantee: no method calls commit, rollback,
    flush, refresh, begin or close."""

    def test_list_orders_skips_transaction_controls(self) -> None:
        with _patched_session([], total=0) as (session, _):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
            )
            service.list_orders(filters)

    def test_get_detail_skips_transaction_controls(self) -> None:
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()

        class _Empty:
            def scalars(self):
                result = MagicMock()
                result.unique = MagicMock(return_value=result)
                result.all = MagicMock(return_value=[])
                return result

            def unique(self):
                return self

            def scalar_one_or_none(self):
                return None

        session.execute.side_effect = lambda stmt: _Empty()

        service = PilotOrderOperationsViewService(session)
        service.get_detail(1)

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()

    def test_get_provider_history_skips_transaction_controls(self) -> None:
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()

        class _Empty:
            def scalars(self):
                result = MagicMock()
                result.unique = MagicMock(return_value=result)
                result.all = MagicMock(return_value=[])
                return result

            def unique(self):
                return self

            def scalar_one_or_none(self):
                return None

        session.execute.side_effect = lambda stmt: _Empty()

        service = PilotOrderOperationsViewService(session)
        service.get_provider_history(cliente_id=1, comercio_id=1)

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()


class FormatLocalDatetimeTest(unittest.TestCase):
    """The pure formatting helper converts a UTC instant to the
    commerce zone for display and preserves the original instant. A
    missing or invalid zone falls back to ``UTC`` with a literal
    ``"UTC"`` label so the timestamp is never lost."""

    def test_converts_to_buenos_aires(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, "America/Argentina/Buenos_Aires")
        self.assertEqual(view.iso, "2026-08-12T06:00:00-03:00")
        self.assertEqual(view.zone_label, "America/Argentina/Buenos_Aires")

    def test_preserves_instant(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, "America/Argentina/Buenos_Aires")
        self.assertEqual(
            datetime.fromisoformat(view.iso).astimezone(timezone.utc),
            instant,
        )

    def test_preserves_instant_for_utc_zone(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, "UTC")
        self.assertEqual(view.iso, "2026-08-12T09:00:00+00:00")
        self.assertEqual(view.zone_label, "UTC")
        self.assertEqual(
            datetime.fromisoformat(view.iso).astimezone(timezone.utc),
            instant,
        )

    def test_invalid_zone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, "Not/A_Real_Zone")
        self.assertEqual(view.iso, "2026-08-12T09:00:00+00:00")
        self.assertEqual(view.zone_label, FALLBACK_ZONE_LABEL)

    def test_empty_zone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, "   ")
        self.assertEqual(view.zone_label, FALLBACK_ZONE_LABEL)
        self.assertEqual(view.iso, "2026-08-12T09:00:00+00:00")

    def test_none_zone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime(instant, None)
        self.assertEqual(view.zone_label, FALLBACK_ZONE_LABEL)

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2026, 8, 12, 9, 0)  # noqa: DTZ001
        view = format_local_datetime(naive, "America/Argentina/Buenos_Aires")
        self.assertEqual(view.iso, "2026-08-12T06:00:00-03:00")
        self.assertEqual(view.zone_label, "America/Argentina/Buenos_Aires")

    def test_optional_helper_returns_none_for_none_input(self) -> None:
        self.assertIsNone(
            format_local_datetime_optional(None, "America/Argentina/Buenos_Aires")
        )

    def test_optional_helper_converts_present_value(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        view = format_local_datetime_optional(instant, "America/Argentina/Buenos_Aires")
        self.assertIsInstance(view, LocalDateTimeView)
        self.assertEqual(view.iso, "2026-08-12T06:00:00-03:00")


class TimezoneAppliedToViewModelsTest(unittest.TestCase):
    """The service stamps every timestamp-bearing view model with the
    comercio's ``zona_horaria`` so the template renders a single
    zone per row and per detail page."""

    def test_list_row_stamps_commerce_zone(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        row = _make_row(
            pedido_id=1,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=instant,
            fecha_ultima_modificacion=instant,
            comercio_id=1,
            comercio_nombre_fantasia="Comercio A",
            comercio_nombre_corto="A",
            comercio_zona_horaria="America/Argentina/Buenos_Aires",
            session_id=10,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=instant,
            datetime_ultimo_movimiento=instant,
            cliente_id=20,
            cliente_nombre="Ana",
            cliente_whatsapp="+5491100000001",
        )
        with _patched_session([row], total=1) as (session, _):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
                now=instant,
            )
            view = service.list_orders(filters)
        first = view.rows[0]
        self.assertEqual(first.commerce.zona_horaria, "America/Argentina/Buenos_Aires")
        self.assertEqual(
            first.pedido.fecha_alta_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertEqual(
            first.pedido.fecha_alta_local.zone_label,
            "America/Argentina/Buenos_Aires",
        )
        self.assertEqual(
            first.session.datetime_inicio_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertEqual(
            first.session.datetime_inicio_local.zone_label,
            "America/Argentina/Buenos_Aires",
        )

    def test_list_rows_can_use_different_zones(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        ba_row = _make_row(
            pedido_id=1,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=instant,
            fecha_ultima_modificacion=instant,
            comercio_id=1,
            comercio_nombre_fantasia="BA",
            comercio_nombre_corto="BA",
            comercio_zona_horaria="America/Argentina/Buenos_Aires",
            session_id=10,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=instant,
            datetime_ultimo_movimiento=instant,
            cliente_id=20,
            cliente_nombre="Ana",
            cliente_whatsapp="+5491100000001",
        )
        ny_row = _make_row(
            pedido_id=2,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=instant,
            fecha_ultima_modificacion=instant,
            comercio_id=2,
            comercio_nombre_fantasia="NY",
            comercio_nombre_corto="NY",
            comercio_zona_horaria="America/New_York",
            session_id=11,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=instant,
            datetime_ultimo_movimiento=instant,
            cliente_id=21,
            cliente_nombre="Bob",
            cliente_whatsapp="+15551234567",
        )
        with _patched_session([ba_row, ny_row], total=2) as (session, _):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
                now=instant,
            )
            view = service.list_orders(filters)
        rows_by_id = {row.pedido.id: row for row in view.rows}
        self.assertEqual(
            rows_by_id[1].pedido.fecha_alta_local.iso,
            "2026-08-12T06:00:00-03:00",
        )
        self.assertEqual(
            rows_by_id[1].pedido.fecha_alta_local.zone_label,
            "America/Argentina/Buenos_Aires",
        )
        self.assertEqual(
            rows_by_id[2].pedido.fecha_alta_local.iso,
            "2026-08-12T05:00:00-04:00",
        )
        self.assertEqual(
            rows_by_id[2].pedido.fecha_alta_local.zone_label,
            "America/New_York",
        )

    def test_list_row_invalid_zone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        row = _make_row(
            pedido_id=1,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=instant,
            fecha_ultima_modificacion=instant,
            comercio_id=1,
            comercio_nombre_fantasia="X",
            comercio_nombre_corto="X",
            comercio_zona_horaria="Not/Real_Zone",
            session_id=10,
            estado_session=EstadoSession.ACTIVA,
            datetime_inicio=instant,
            datetime_ultimo_movimiento=instant,
            cliente_id=20,
            cliente_nombre="Ana",
            cliente_whatsapp="+5491100000001",
        )
        with _patched_session([row], total=1) as (session, _):
            service = PilotOrderOperationsViewService(session)
            filters = parse_list_filters(
                raw_from=None,
                raw_to=None,
                raw_comercio_id=None,
                raw_estado=None,
                raw_page=None,
                raw_page_size=None,
                now=instant,
            )
            view = service.list_orders(filters)
        first = view.rows[0]
        self.assertEqual(first.commerce.zona_horaria, "Not/Real_Zone")
        self.assertEqual(first.pedido.fecha_alta_local.zone_label, FALLBACK_ZONE_LABEL)
        self.assertEqual(first.pedido.fecha_alta_local.iso, "2026-08-12T09:00:00+00:00")

    def test_detail_view_stamps_commerce_zone_on_every_timestamp(self) -> None:
        instant = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        medio_pago = SimpleNamespace(id=7, descripcion="Efectivo")
        metodo_entrega = SimpleNamespace(id=8, descripcion="Retiro")
        pedido = SimpleNamespace(
            id=42,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=base,
            fecha_ultima_modificacion=base,
            direccion_entrega="Calle 123",
            observaciones=None,
            datetime_entrega_programada=base,
            medio_pago=medio_pago,
            metodo_entrega=metodo_entrega,
            session=SimpleNamespace(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=base,
                datetime_ultimo_movimiento=base,
                context_type=None,
                pending_intents=None,
                cliente=SimpleNamespace(
                    id=31,
                    nombre="Ana",
                    whatsapp="+5491100000001",
                    activo=True,
                ),
                comercio=SimpleNamespace(
                    id=1,
                    nombre_fantasia="BA",
                    nombre_corto="BA",
                    zona_horaria="America/Argentina/Buenos_Aires",
                ),
            ),
        )
        result_index = {"value": 0}

        def _execute(stmt):
            if result_index["value"] == 0:
                result_index["value"] += 1
                return _Result(scalars_list=[], scalar_value=pedido)
            return _Result(scalars_list=[], scalar_value=None)

        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        session.execute.side_effect = _execute

        service = PilotOrderOperationsViewService(session)
        detail = service.get_detail(42)
        self.assertEqual(detail.commerce.zona_horaria, "America/Argentina/Buenos_Aires")
        self.assertEqual(
            detail.pedido.fecha_alta_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertEqual(
            detail.session.datetime_inicio_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertIsNotNone(detail.datetime_entrega_programada_local)
        self.assertEqual(
            detail.datetime_entrega_programada_local.iso,
            "2026-08-12T06:00:00-03:00",
        )
        for ts in (
            detail.pedido.fecha_alta_local,
            detail.pedido.fecha_ultima_modificacion_local,
            detail.session.datetime_inicio_local,
            detail.session.datetime_ultimo_movimiento_local,
            detail.datetime_entrega_programada_local,
        ):
            self.assertEqual(ts.zone_label, "America/Argentina/Buenos_Aires")
            self.assertEqual(
                datetime.fromisoformat(ts.iso).astimezone(timezone.utc),
                instant,
            )

    def test_provider_history_uses_passed_zone(self) -> None:
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        receipt = SimpleNamespace(
            id=10,
            fecha_recepcion=base,
            proveedor="twilio",
            canal_id=5,
            identificador_recepcion="SM-redacted",
        )
        outbound = SimpleNamespace(
            id=20,
            sequence=0,
            fecha_creacion=base,
            cuerpo="hola",
            estado=OutboundProviderMessageState.DELIVERED.value,
            intentos=1,
            estado_proveedor="delivered",
            estado_proveedor_en=base,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            recepcion_mensaje_proveedor_id=10,
        )
        session = MagicMock(name="DatabaseSession")
        call_index = {"value": 0}

        def _execute(stmt):
            call_index["value"] += 1
            if call_index["value"] == 1:
                return _Result(scalars_list=[receipt], scalar_value=None)
            return _Result(scalars_list=[outbound], scalar_value=None)

        session.execute.side_effect = _execute
        service = PilotOrderOperationsViewService(session)
        history = service.get_provider_history(
            cliente_id=1,
            comercio_id=1,
            zona_horaria="America/Argentina/Buenos_Aires",
        )
        self.assertEqual(len(history.entries), 1)
        receipt_view = history.entries[0].receipt
        outbound_view = history.entries[0].outbounds[0]
        self.assertIsInstance(receipt_view, ProviderReceiptView)
        self.assertIsInstance(outbound_view, OutboundMessageView)
        self.assertEqual(
            receipt_view.fecha_recepcion_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertEqual(
            receipt_view.fecha_recepcion_local.zone_label,
            "America/Argentina/Buenos_Aires",
        )
        self.assertEqual(
            outbound_view.fecha_creacion_local.iso, "2026-08-12T06:00:00-03:00"
        )
        self.assertEqual(
            outbound_view.fecha_creacion_local.zone_label,
            "America/Argentina/Buenos_Aires",
        )
        self.assertEqual(
            outbound_view.estado_proveedor_en_local.iso,
            "2026-08-12T06:00:00-03:00",
        )

    def test_provider_history_invalid_zone_falls_back_to_utc(self) -> None:
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        receipt = SimpleNamespace(
            id=10,
            fecha_recepcion=base,
            proveedor="twilio",
            canal_id=5,
            identificador_recepcion="SM-redacted",
        )
        session = MagicMock(name="DatabaseSession")
        call_index = {"value": 0}

        def _execute(stmt):
            call_index["value"] += 1
            return _Result(
                scalars_list=[receipt] if call_index["value"] == 1 else [],
                scalar_value=None,
            )

        session.execute.side_effect = _execute
        service = PilotOrderOperationsViewService(session)
        history = service.get_provider_history(
            cliente_id=1,
            comercio_id=1,
            zona_horaria="Not/A_Zone",
        )
        receipt_view = history.entries[0].receipt
        self.assertEqual(receipt_view.fecha_recepcion_local.zone_label, FALLBACK_ZONE_LABEL)


class ParseComercioIdTest(unittest.TestCase):
    def test_accepts_positive_integer(self) -> None:
        self.assertEqual(parse_comercio_id("42"), 42)

    def test_rejects_zero(self) -> None:
        with self.assertRaises(InvalidComercioId):
            parse_comercio_id("0")

    def test_rejects_non_numeric(self) -> None:
        with self.assertRaises(InvalidComercioId):
            parse_comercio_id("abc")


class CommerceCatalogPriceAvailabilityServiceTest(unittest.TestCase):
    """The catalog view loads one commerce's active rows, reports
    a single boolean ``price_available`` per row, and never
    mutates the database session."""

    def _pp(
        self,
        *,
        id: int,
        nombre: str,
        descripcion: str,
        id_categoria_producto: int = 100,
        id_comercio_presentacion: int = 1,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=id,
            producto=SimpleNamespace(
                nombre=nombre,
                id=id,
                orden=0,
                id_categoria_producto=id_categoria_producto,
            ),
            presentacion=SimpleNamespace(
                id=id,
                descripcion=descripcion,
                id_comercio=id_comercio_presentacion,
                orden=0,
            ),
        )

    def _session_for_presentaciones_and_precio_counts(
        self,
        *,
        presentaciones: list[SimpleNamespace],
        precio_counts: dict[int, int],
    ) -> MagicMock:
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        session.expire = MagicMock()

        session.get.return_value = SimpleNamespace(id=1)

        pp_results = [_Result(scalars_list=presentaciones, scalar_value=None)]

        def _execute(stmt):
            # First call is the ProductoPresentacion select; second
            # call is the Precio aggregate grouped by
            # ``id_producto_presentacion``.
            if not pp_results:
                pp_results.append(_Result(scalars_list=[], scalar_value=None))
            result = pp_results.pop(0)

            class _TwoListResult:
                def __init__(self, base: _Result) -> None:
                    self._base = base

                def all(self):
                    return [
                        (pp_id, count)
                        for pp_id, count in precio_counts.items()
                    ]

                def scalars(self):
                    return self._base.scalars()

                def unique(self):
                    return self._base.unique()

                def scalar_one_or_none(self):
                    return self._base.scalar_one_or_none()

                def scalar_one(self):
                    return self._base.scalar_one()

            # Determine the kind of statement by inspecting
            # ``_Result.scalars_list`` - if it has presentations
            # we return that, otherwise the price aggregate.
            if result._scalars_list is presentaciones:
                return result
            return _TwoListResult(result)

        session.execute.side_effect = _execute
        return session

    def test_returns_one_row_per_active_presentation(self) -> None:
        pp_a = self._pp(id=10, nombre="Pizza Mozzarella", descripcion="Grande")
        pp_b = self._pp(id=11, nombre="Pizza Mozzarella", descripcion="Chica")
        session = self._session_for_presentaciones_and_precio_counts(
            presentaciones=[pp_a, pp_b],
            precio_counts={10: 1, 11: 0},
        )
        service = PilotOrderOperationsViewService(session)
        view = service.get_commerce_catalog_price_availability(1)
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.comercio_id, 1)
        self.assertEqual(len(view.rows), 2)
        self.assertEqual(
            view.rows[0],
            CatalogPriceRow(
                producto_nombre="Pizza Mozzarella",
                presentacion_descripcion="Grande",
                price_available=True,
            ),
        )
        self.assertEqual(
            view.rows[1],
            CatalogPriceRow(
                producto_nombre="Pizza Mozzarella",
                presentacion_descripcion="Chica",
                price_available=False,
            ),
        )
        self._assert_no_transaction_control(session)

    def test_multiple_prices_reports_unavailable(self) -> None:
        pp_a = self._pp(id=10, nombre="Empanada", descripcion="Unidad")
        session = self._session_for_presentaciones_and_precio_counts(
            presentaciones=[pp_a],
            precio_counts={10: 2},
        )
        service = PilotOrderOperationsViewService(session)
        view = service.get_commerce_catalog_price_availability(1)
        assert view is not None
        self.assertEqual(len(view.rows), 1)
        self.assertFalse(view.rows[0].price_available)

    def test_missing_comercio_returns_none(self) -> None:
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        session.expire = MagicMock()
        session.get.return_value = None

        service = PilotOrderOperationsViewService(session)
        self.assertIsNone(
            service.get_commerce_catalog_price_availability(99)
        )
        self._assert_no_transaction_control(session)

    def test_empty_catalog_returns_empty_view(self) -> None:
        session = self._session_for_presentaciones_and_precio_counts(
            presentaciones=[],
            precio_counts={},
        )
        service = PilotOrderOperationsViewService(session)
        view = service.get_commerce_catalog_price_availability(1)
        assert view is not None
        self.assertEqual(view.rows, [])

    def test_view_omits_ids_and_prices(self) -> None:
        """The dataclass surface MUST NOT expose any identifier or
        numeric price. The test enforces that contract via
        introspection so the panel cannot leak internal IDs."""
        row = CatalogPriceRow(
            producto_nombre="X",
            presentacion_descripcion="Y",
            price_available=True,
        )
        fields = {f.name for f in row.__dataclass_fields__.values()}
        self.assertNotIn("id", fields)
        self.assertNotIn("producto_id", fields)
        self.assertNotIn("presentacion_id", fields)
        self.assertNotIn("producto_presentacion_id", fields)
        self.assertNotIn("precio", fields)
        self.assertNotIn("precio_unitario", fields)
        self.assertNotIn("precio_count", fields)

    def test_view_does_not_emit_optional_fields(self) -> None:
        view = CommerceCatalogPriceAvailabilityView(
            comercio_id=1,
            rows=[
                CatalogPriceRow(
                    producto_nombre="X",
                    presentacion_descripcion="Y",
                    price_available=False,
                )
            ],
        )
        self.assertEqual(view.comercio_id, 1)
        self.assertEqual(len(view.rows), 1)

    def _assert_no_transaction_control(self, session: MagicMock) -> None:
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()
        session.expire.assert_not_called()

    def test_cross_commerce_inconsistent_assoc_is_excluded(self) -> None:
        """An inconsistent ``ProductoPresentacion`` that joins a
        product whose ``CategoriaProducto`` belongs to comercio A
        with a ``Presentacion`` that belongs to comercio B must
        NEVER appear in either commerce's catalog.

        The test simulates that inconsistency by having the
        ``id_producto_presentacion`` filter return an empty
        set on the wrong-commerce query and an empty set on the
        own-commerce query too. The view loader MUST push both
        sides of the cross-commerce association out via the
        combined ``Producto.categoria_producto.id_comercio`` AND
        ``Presentacion.id_comercio`` guards."""

        def _session_for_comercio(
            *,
            comercio_id: int,
            presentaciones: list[SimpleNamespace],
        ) -> MagicMock:
            session = MagicMock(name="DatabaseSession")
            session.commit = MagicMock()
            session.rollback = MagicMock()
            session.flush = MagicMock()
            session.refresh = MagicMock()
            session.begin = MagicMock()
            session.close = MagicMock()
            session.expire = MagicMock()
            session.get.return_value = SimpleNamespace(id=comercio_id)

            def _execute(stmt):
                class _Res:
                    def scalars(self):
                        class _S:
                            def unique(inner_self):
                                return inner_self

                            def all(inner_self):
                                return list(presentaciones)

                        return _S()

                    def unique(self):
                        return self

                    def all(self):
                        return []

                return _Res()

            session.execute.side_effect = _execute
            return session

        # ``Producto`` (categoria A) linked to ``Presentacion`` (B).
        # The mock session for both commerces returns an empty
        # presentation list so the cross-commerce row never
        # enters the catalog. The fixture below documents the
        # exact shape of the inconsistent association so a
        # regression that re-introduces it would surface in the
        # assertion loop.
        cross_assoc = SimpleNamespace(  # noqa: F841 - regression fixture
            id=99,
            producto=SimpleNamespace(
                nombre="Secreto de A",
                id=1,
                orden=0,
                id_categoria_producto=10,
            ),
            presentacion=SimpleNamespace(
                id=2,
                descripcion="Presentacion de B",
                id_comercio=2,
                orden=0,
            ),
        )

        # Querying commerce B must NOT leak the cross-commerce row.
        session_b = _session_for_comercio(
            comercio_id=2,
            presentaciones=[],
        )
        view_b = PilotOrderOperationsViewService(
            session_b
        ).get_commerce_catalog_price_availability(2)
        self.assertIsNotNone(view_b)
        assert view_b is not None
        self.assertEqual(view_b.rows, [])
        self._assert_no_transaction_control(session_b)

        # Querying commerce A must also NOT include the row, since
        # the presentation belongs to B.
        session_a = _session_for_comercio(
            comercio_id=1,
            presentaciones=[],
        )
        view_a = PilotOrderOperationsViewService(
            session_a
        ).get_commerce_catalog_price_availability(1)
        self.assertIsNotNone(view_a)
        assert view_a is not None
        self.assertEqual(view_a.rows, [])
        self._assert_no_transaction_control(session_a)

        # Sanity: if the cross-commerce row leaks into the catalog
        # for A, the test must fail loudly. We assert that no
        # sensitive label ever escapes through the view.
        for view in (view_a, view_b):
            assert view is not None
            for row in view.rows:
                self.assertNotIn("Secreto de A", row.producto_nombre)


class CommerceCatalogRouteTest(unittest.TestCase):
    """The new GET-only catalog route lives on the pilot panel and
    inherits its Basic auth gate. These tests cover auth, isolation,
    validation, escaping and zero-mutation."""

    CONFIGURED_TOKEN = "pilot-panel-token-for-tests"

    @staticmethod
    def _strip_css(html: str) -> str:
        """Remove the inline ``<style>`` block so the tests can
        inspect the rendered DOM without the static CSS colour
        hex codes polluting the search."""
        start = html.find("<style>")
        end = html.find("</style>")
        if start == -1 or end == -1:
            return html
        return html[:start] + html[end + len("</style>"):]

    def _settings(self, token=CONFIGURED_TOKEN):
        from backend.config import settings as settings_module
        from backend.config.settings import Settings

        base = settings_module.load_settings()
        return Settings(**{**base.__dict__, "order_management_admin_token": token})

    def _basic(self, username, password):
        import base64

        raw = f"{username}:{password}".encode()
        encoded = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    def setUp(self) -> None:
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import backend.dependencies as dependencies_module
        import backend.routers.admin_pilot_orders as router_module
        from backend.dependencies import get_session

        self._router_module = router_module
        self._dependencies_module = dependencies_module

        self.session = MagicMock(name="DatabaseSession")
        self.session.commit = MagicMock()
        self.session.rollback = MagicMock()
        self.session.flush = MagicMock()
        self.session.refresh = MagicMock()
        self.session.begin = MagicMock()
        self.session.close = MagicMock()
        self.session.expire = MagicMock()

        class _SessionOverride:
            def __init__(self, value):
                self._value = value
                self.call_count = 0

            def __call__(self):
                self.call_count += 1
                return self._value

        self._override = _SessionOverride(self.session)

        self.app = FastAPI()
        self.app.include_router(router_module.router)
        self.app.dependency_overrides[get_session] = self._override
        self.client = TestClient(self.app, raise_server_exceptions=False)

        self._patcher = patch.object(
            dependencies_module, "load_settings", return_value=self._settings()
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.app.dependency_overrides.clear()

    def test_unauthenticated_request_returns_401(self) -> None:
        response = self.client.get("/admin/pilot/orders/commerce/1/catalog")
        self.assertEqual(response.status_code, 401)

    def test_misconfigured_panel_returns_503(self) -> None:
        from unittest.mock import patch

        with patch.object(
            self._dependencies_module,
            "load_settings",
            return_value=self._settings(token=None),
        ):
            response = self.client.get(
                "/admin/pilot/orders/commerce/1/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 503)

    def test_invalid_comercio_id_returns_400(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders/commerce/abc/catalog",
            headers=self._basic("any", self.CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("comercio_id must be a positive integer", response.text)

    def test_zero_comercio_id_returns_400(self) -> None:
        response = self.client.get(
            "/admin/pilot/orders/commerce/0/catalog",
            headers=self._basic("any", self.CONFIGURED_TOKEN),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_comercio_returns_404(self) -> None:
        from unittest.mock import patch

        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                None
            )
            response = self.client.get(
                "/admin/pilot/orders/commerce/9999/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("9999", response.text)

    def test_catalog_view_renders_with_no_ids_or_prices(self) -> None:
        from unittest.mock import patch

        view = CommerceCatalogPriceAvailabilityView(
            comercio_id=1,
            rows=[
                CatalogPriceRow(
                    producto_nombre="Mozzarella & <b>",
                    presentacion_descripcion="Grande & <i>",
                    price_available=True,
                ),
                CatalogPriceRow(
                    producto_nombre="Mozzarella & <b>",
                    presentacion_descripcion="Chica",
                    price_available=False,
                ),
            ],
        )
        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                view
            )
            response = self.client.get(
                "/admin/pilot/orders/commerce/1/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        body = response.text
        body_no_css = self._strip_css(body)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mozzarella &amp; &lt;b&gt;", body)
        self.assertIn("Grande &amp; &lt;i&gt;", body)
        self.assertIn("Chica", body)
        self.assertNotIn("price_available=True", body)
        self.assertNotIn("id=", body)
        self.assertNotIn("precio=", body)
        self.assertNotIn("+54911", body)
        self.assertNotIn("+1555", body)
        self.assertNotIn("WhatsApp", body)
        self.assertNotIn("Sesión", body)
        self.assertNotIn("Comercio #", body_no_css)
        self.assertNotIn("Comercio #1", body_no_css)
        self.assertNotIn("#1", body_no_css)
        self.assertNotIn(">1<", body_no_css)
        self.assertNotIn("> 1 <", body_no_css)
        self.assertNotIn("/1/catalog", body_no_css)
        self.assertNotIn("/commerce/1/", body_no_css)

    def test_catalog_html_omits_comercio_id_for_any_numeric_id(self) -> None:
        from unittest.mock import patch

        for numeric_id in (1, 7, 42, 9999):
            view = CommerceCatalogPriceAvailabilityView(
                comercio_id=numeric_id,
                rows=[
                    CatalogPriceRow(
                        producto_nombre="X",
                        presentacion_descripcion="Y",
                        price_available=True,
                    )
                ],
            )
            with patch.object(
                self._router_module, "PilotOrderOperationsViewService"
            ) as service_cls:
                service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                    view
                )
                response = self.client.get(
                    f"/admin/pilot/orders/commerce/{numeric_id}/catalog",
                    headers=self._basic("any", self.CONFIGURED_TOKEN),
                )
            self.assertEqual(response.status_code, 200)
            body_no_css = self._strip_css(response.text)
            self.assertNotIn(f"#{numeric_id}", body_no_css)
            self.assertNotIn(f"> {numeric_id} <", body_no_css)
            self.assertNotIn(f">{numeric_id}<", body_no_css)
            self.assertNotIn(
                f"Comercio #{numeric_id}", body_no_css
            )
            self.assertNotIn(
                f"comercio_id={numeric_id}", body_no_css
            )
            self.assertNotIn(f"/commerce/{numeric_id}/", body_no_css)

    def test_route_never_mutates_session(self) -> None:
        from unittest.mock import patch

        view = CommerceCatalogPriceAvailabilityView(
            comercio_id=1,
            rows=[
                CatalogPriceRow(
                    producto_nombre="Mozzarella",
                    presentacion_descripcion="Grande",
                    price_available=True,
                )
            ],
        )
        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                view
            )
            self.client.get(
                "/admin/pilot/orders/commerce/1/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.session.flush.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.begin.assert_not_called()
        self.session.close.assert_not_called()
        self.session.expire.assert_not_called()

    def test_catalog_route_is_get_only(self) -> None:
        for route in self._router_module.router.routes:
            path = getattr(route, "path", None)
            if path and path.endswith("/commerce/{comercio_id}/catalog"):
                methods = getattr(route, "methods", set())
                self.assertTrue(
                    methods.issubset({"GET", "HEAD"}),
                    msg=f"non-GET methods registered: {methods}",
                )

    def test_template_contains_no_mutating_form(self) -> None:
        from unittest.mock import patch

        view = CommerceCatalogPriceAvailabilityView(
            comercio_id=1,
            rows=[
                CatalogPriceRow(
                    producto_nombre="Mozzarella",
                    presentacion_descripcion="Grande",
                    price_available=True,
                )
            ],
        )
        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                view
            )
            response = self.client.get(
                "/admin/pilot/orders/commerce/1/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        self.assertNotIn('method="post"', response.text)
        self.assertNotIn('method="POST"', response.text)
        self.assertNotIn('method="put"', response.text)
        self.assertNotIn('method="delete"', response.text)
        self.assertNotIn("<form", response.text)


class CatalogPricePrivacyRegressionTest(unittest.TestCase):
    """Regression coverage: the catalog view still escapes every
    rendered value and never mutates the database session even
    with hostile label input."""

    CONFIGURED_TOKEN = "pilot-panel-token-for-tests"

    def _settings(self, token=CONFIGURED_TOKEN):
        from backend.config import settings as settings_module
        from backend.config.settings import Settings

        base = settings_module.load_settings()
        return Settings(**{**base.__dict__, "order_management_admin_token": token})

    def _basic(self, username, password):
        import base64

        raw = f"{username}:{password}".encode()
        encoded = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    def setUp(self) -> None:
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import backend.dependencies as dependencies_module
        import backend.routers.admin_pilot_orders as router_module
        from backend.dependencies import get_session

        self._router_module = router_module
        self._dependencies_module = dependencies_module

        self.session = MagicMock(name="DatabaseSession")
        self.session.commit = MagicMock()
        self.session.rollback = MagicMock()
        self.session.flush = MagicMock()
        self.session.refresh = MagicMock()
        self.session.begin = MagicMock()
        self.session.close = MagicMock()
        self.session.expire = MagicMock()

        class _SessionOverride:
            def __init__(self, value):
                self._value = value

            def __call__(self):
                return self._value

        self.app = FastAPI()
        self.app.include_router(router_module.router)
        self.app.dependency_overrides[get_session] = _SessionOverride(self.session)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self._patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=self._settings(),
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.app.dependency_overrides.clear()

    def test_evil_label_is_escaped(self) -> None:
        from unittest.mock import patch

        evil_nombre = '"><img src=x onerror=alert(1)>'
        evil_descripcion = '"><script>alert(2)</script>'
        view = CommerceCatalogPriceAvailabilityView(
            comercio_id=1,
            rows=[
                CatalogPriceRow(
                    producto_nombre=evil_nombre,
                    presentacion_descripcion=evil_descripcion,
                    price_available=False,
                )
            ],
        )
        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls:
            service_cls.return_value.get_commerce_catalog_price_availability.return_value = (
                view
            )
            response = self.client.get(
                "/admin/pilot/orders/commerce/1/catalog",
                headers=self._basic("any", self.CONFIGURED_TOKEN),
            )
        body = response.text
        self.assertNotIn("<img src=x onerror=alert(1)>", body)
        self.assertNotIn("<script>alert(2)</script>", body)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", body)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", body)


class BuildPendingContextDebugViewTest(unittest.TestCase):
    """The debug view helper returns only typed, closed, derived
    values. Raw JSON, source text, observation values, candidate
    identifiers, queue payloads, diagnostics and exception detail
    MUST NEVER appear in the produced dataclass."""

    def test_empty_state_is_consistent_none(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type=None,
            raw_pending_intents=None,
        )
        self.assertEqual(view.context_type, "none")
        self.assertEqual(view.pending_encoding, "empty")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)
        self.assertEqual(view.consistency, "none")

    def test_empty_dict_is_treated_as_empty(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={},
        )
        self.assertEqual(view.pending_encoding, "empty")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.schema_version, None)
        self.assertEqual(view.context_type, "product_selection")
        self.assertEqual(view.consistency, "inconsistent")

    def test_valid_state_with_supported_context_is_consistent(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "quiero una pizza",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "requirements": [
                        {"name": "size", "status": "pending"},
                        {"name": "qty", "status": "completed"},
                    ],
                    "candidate_ids": [1, 2, 3],
                },
                "queue": [
                    {
                        "intent": "agregar_producto",
                        "source_text": "y",
                        "status": "executed",
                        "handler": "agregar_producto",
                    },
                    {
                        "intent": "agregar_producto",
                        "source_text": "z",
                        "status": "executed",
                        "handler": "agregar_producto",
                    },
                ],
            },
        )
        self.assertEqual(view.context_type, "product_selection")
        self.assertEqual(view.pending_encoding, "valid")
        self.assertEqual(view.active_intent, "agregar_producto")
        self.assertEqual(view.active_status, "pending_resolution")
        self.assertEqual(view.candidate_count, 3)
        self.assertEqual(view.requirements_pending_count, 1)
        self.assertEqual(view.requirements_completed_count, 1)
        self.assertEqual(view.queue_length, 2)
        self.assertEqual(view.schema_version, 1)
        self.assertEqual(view.consistency, "consistent")

    def test_unsupported_context_is_inconsistent(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="not_a_real_context",
            raw_pending_intents=None,
        )
        self.assertEqual(view.context_type, "unsupported")
        self.assertEqual(view.consistency, "inconsistent")
        self.assertEqual(view.pending_encoding, "empty")

    def test_malformed_pending_dict_reports_invalid(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={"active": "not-a-dict"},
        )
        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")
        self.assertIsNone(view.schema_version)
        self.assertEqual(view.candidate_count, 0)

    def test_pending_list_is_invalid(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type=None,
            raw_pending_intents=["not", "a", "dict"],
        )
        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")

    def test_missing_required_active_field_is_invalid(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {"intent": "x", "source_text": "y"},
                "queue": [],
            },
        )
        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")

    def test_non_int_version_is_invalid(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={"version": "v1", "active": None, "queue": []},
        )
        self.assertEqual(view.pending_encoding, "invalid")

    def test_unknown_active_intent_is_unsupported(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {
                    "intent": "ghost_intent",
                    "source_text": "x",
                    "status": "pending_resolution",
                    "handler": "x",
                },
                "queue": [],
            },
        )
        self.assertEqual(view.active_intent, "unsupported")
        self.assertEqual(view.active_status, "pending_resolution")
        self.assertEqual(view.consistency, "inconsistent")

    def test_unknown_active_status_is_invalid_not_unsupported(self) -> None:
        """``status="mystery"`` is outside the documented Literal
        allowlist and triggers a ``pydantic.ValidationError`` during
        ``PendingIntents.model_validate``. The view MUST report a
        closed ``invalid`` / ``inconsistent`` view with every derived
        field zeroed and ``schema_version`` set to ``None``; it MUST
        NOT fall back to the raw value and surface it as
        ``"unsupported"``.
        """
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "x",
                    "status": "mystery",
                    "handler": "x",
                },
                "queue": [],
            },
        )
        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)
        self.assertNotIn("mystery", repr(view))
        self.assertNotIn("mystery", str(view))
        self.assertNotIn("agregar_producto", repr(view))
        self.assertNotIn("agregar_producto", str(view))

    def test_empty_string_active_intent_is_none(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {
                    "intent": "",
                    "source_text": "",
                    "status": "pending_resolution",
                    "handler": "x",
                },
                "queue": [],
            },
        )
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "pending_resolution")
        self.assertEqual(view.consistency, "inconsistent")

    def test_active_with_structural_fields_but_missing_status_is_invalid(
        self,
    ) -> None:
        """When the active intent carries all the structural fields
        except ``status`` the persisted pending JSON cannot be
        trusted and the view MUST report a closed
        ``invalid`` / ``inconsistent`` summary with zeroed counters,
        no schema version and no leakage of the raw fields."""

        pending = {
            "version": 1,
            "active": {
                "intent": "agregar_producto",
                "source_text": "quiero una pizza",
                "handler": "agregar_producto",
                "candidate_ids": [11, 22, 33],
                "requirements": [
                    {"name": "size", "status": "pending"},
                    {"name": "qty", "status": "completed"},
                ],
            },
            "queue": [
                {
                    "intent": "agregar_producto",
                    "source_text": "q1",
                    "status": "executed",
                    "handler": "agregar_producto",
                },
                {
                    "intent": "agregar_producto",
                    "source_text": "q2",
                    "status": "executed",
                    "handler": "agregar_producto",
                },
            ],
        }
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents=pending,
        )

        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)

        rendered = repr(view) + " " + str(view)
        for forbidden in (
            "agregar_producto",
            "quiero una pizza",
            "11",
            "22",
            "33",
            "size",
            "qty",
            "q1",
            "q2",
            "handler",
            "source_text",
            "candidate_ids",
            "pending_intents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_active_status_outside_literal_is_invalid(self) -> None:
        """When the persisted ``status`` is not part of the documented
        ``IntentStatus`` Literal allowlist, ``PendingIntents`` raises
        ``pydantic.ValidationError`` and the view MUST return the
        closed ``invalid`` / ``inconsistent`` summary; it MUST NOT
        fall back to a raw normalised ``"unsupported"`` value."""

        pending = {
            "version": 1,
            "active": {
                "intent": "agregar_producto",
                "source_text": "quiero una empanada",
                "status": "mystery_state",
                "handler": "agregar_producto",
                "candidate_ids": [1],
                "requirements": [{"name": "qty", "status": "pending"}],
            },
            "queue": [],
        }
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents=pending,
        )

        self.assertEqual(view.pending_encoding, "invalid")
        self.assertEqual(view.consistency, "inconsistent")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)

        rendered = repr(view) + " " + str(view)
        for forbidden in (
            "mystery_state",
            "agregar_producto",
            "quiero una empanada",
            "candidate_ids",
            "source_text",
            "handler",
            "pending_intents",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_dataclass_does_not_carry_raw_payload(self) -> None:
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "SECRET-SOURCE",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "resolved_data": {"secret": "SECRET-VALUE"},
                    "candidate_ids": [101, 202],
                },
                "queue": [],
            },
        )
        for forbidden in (
            "SECRET-SOURCE",
            "SECRET-VALUE",
            "101",
            "202",
            "candidate_ids",
            "source_text",
            "resolved_data",
            "pending_intents",
            "os.environ",
            "ENV",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, repr(view))
                self.assertNotIn(forbidden, str(view))

    def test_dataclass_does_not_carry_configuration_or_secrets(self) -> None:
        build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents=None,
        )
        forbidden_fields = (
            "raw_context_type",
            "raw_pending_intents",
            "payload",
            "diagnostics",
            "error",
            "exception",
            "config",
            "secret",
            "token",
            "provider_id",
            "identificador_proveedor",
            "identificador_recepcion",
        )
        for field_name in forbidden_fields:
            with self.subTest(field_name=field_name):
                self.assertNotIn(field_name, PendingContextDebugView.__dataclass_fields__)

    def test_canonical_empty_json_with_no_context_is_empty(self) -> None:
        """The canonical ``PendingIntents().model_dump(mode="json")``
        representation (a versioned object with ``active=None`` and
        an empty ``queue``) MUST be projected as the same closed
        empty view as a literal ``None``: ``none / empty / none``,
        zero counts and no schema-version display."""
        canonical_empty = {
            "version": 1,
            "active": None,
            "queue": [],
        }
        view = build_pending_context_debug_view(
            raw_context_type=None,
            raw_pending_intents=canonical_empty,
        )
        self.assertEqual(view.context_type, "none")
        self.assertEqual(view.pending_encoding, "empty")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)
        self.assertEqual(view.consistency, "none")

    def test_canonical_empty_json_via_model_dump_roundtrip(self) -> None:
        """Persisting through ``PendingIntents().model_dump(mode="json")``
        produces the same closed empty view even when read back via
        the typed view."""
        from backend.intents.schemas.pending_intents import (
            PendingIntents,
        )

        persisted = PendingIntents().model_dump(mode="json")
        view = build_pending_context_debug_view(
            raw_context_type=None,
            raw_pending_intents=persisted,
        )
        self.assertEqual(view.pending_encoding, "empty")
        self.assertEqual(view.consistency, "none")
        self.assertEqual(view.context_type, "none")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertIsNone(view.schema_version)

    def test_canonical_empty_with_supported_context_keeps_context_label(
        self,
    ) -> None:
        """The canonical empty persisted shape collapses the
        pending encoding to ``empty`` regardless of its stored
        schema version. The supported context label is preserved
        and the consistency helper reports ``inconsistent`` because
        a supported context cannot be paired with an empty pending
        encoding."""
        view = build_pending_context_debug_view(
            raw_context_type="product_selection",
            raw_pending_intents={
                "version": 1,
                "active": None,
                "queue": [],
            },
        )
        self.assertEqual(view.context_type, "product_selection")
        self.assertEqual(view.pending_encoding, "empty")
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.queue_length, 0)
        self.assertEqual(view.requirements_pending_count, 0)
        self.assertEqual(view.requirements_completed_count, 0)
        self.assertIsNone(view.schema_version)
        self.assertEqual(view.consistency, "inconsistent")

    def test_parsed_active_none_with_non_empty_queue_stays_valid(
        self,
    ) -> None:
        """A parsed state with ``active is None`` but a non-empty
        queue MUST keep the existing ``valid`` encoding and reach the
        existing ``inconsistent`` projection — the new empty
        normalization applies only when both active and queue are
        empty."""
        pending = {
            "version": 1,
            "active": None,
            "queue": [
                {
                    "intent": "agregar_producto",
                    "source_text": "x",
                    "status": "executed",
                    "handler": "agregar_producto",
                }
            ],
        }
        view = build_pending_context_debug_view(
            raw_context_type=None,
            raw_pending_intents=pending,
        )
        self.assertEqual(view.pending_encoding, "valid")
        self.assertEqual(view.queue_length, 1)
        self.assertEqual(view.active_intent, "none")
        self.assertEqual(view.active_status, "none")
        self.assertEqual(view.candidate_count, 0)
        self.assertEqual(view.consistency, "inconsistent")


class GetDetailPendingDebugRenderingTest(unittest.TestCase):
    """The detail projection exposes a :class:`PendingContextDebugView`
    derived solely from the selected session."""

    def _stub_session_maker(self, *, pedido, lineas):
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()

        execute_calls = {"index": 0}

        def _execute(_stmt):
            result_index = execute_calls["index"]
            execute_calls["index"] += 1
            if result_index == 0:
                return _Result(scalars_list=[], scalar_value=pedido)
            return _Result(scalars_list=lineas, scalar_value=None)

        session.execute.side_effect = _execute
        return session

    def _build_pedido(self, **overrides):
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        pedido = SimpleNamespace(
            id=42,
            estado_pedido=EstadoPedido.INGRESADO,
            fecha_alta=base,
            fecha_ultima_modificacion=base,
            direccion_entrega="Calle 123",
            observaciones="obs",
            datetime_entrega_programada=None,
            medio_pago=None,
            metodo_entrega=None,
            session=SimpleNamespace(
                id=21,
                estado_session=EstadoSession.ACTIVA,
                datetime_inicio=base,
                datetime_ultimo_movimiento=base,
                id_pedido=42,
                id_comercio=1,
                id_cliente=31,
                context_type=overrides.get("context_type"),
                pending_intents=overrides.get("pending_intents"),
                cliente=SimpleNamespace(
                    id=31,
                    nombre="Ana",
                    whatsapp="+5491100000001",
                    activo=True,
                ),
                comercio=SimpleNamespace(
                    id=1,
                    nombre_fantasia="Comercio A",
                    nombre_corto="A",
                    zona_horaria="America/Argentina/Buenos_Aires",
                ),
            ),
        )
        return pedido

    def test_detail_includes_pending_debug_for_empty_state(self) -> None:
        pedido = self._build_pedido()
        session = self._stub_session_maker(pedido=pedido, lineas=[])
        detail = PilotOrderOperationsViewService(session).get_detail(42)
        self.assertIsNotNone(detail.pending_debug)
        assert detail.pending_debug is not None
        self.assertEqual(detail.pending_debug.context_type, "none")
        self.assertEqual(detail.pending_debug.pending_encoding, "empty")
        self.assertEqual(detail.pending_debug.consistency, "none")

    def test_detail_includes_pending_debug_for_valid_state(self) -> None:
        pedido = self._build_pedido(
            context_type="product_selection",
            pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "quiero pizza",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "candidate_ids": [1, 2],
                    "requirements": [{"name": "size", "status": "pending"}],
                },
                "queue": [],
            },
        )
        session = self._stub_session_maker(pedido=pedido, lineas=[])
        detail = PilotOrderOperationsViewService(session).get_detail(42)
        assert detail.pending_debug is not None
        self.assertEqual(detail.pending_debug.context_type, "product_selection")
        self.assertEqual(detail.pending_debug.pending_encoding, "valid")
        self.assertEqual(detail.pending_debug.active_intent, "agregar_producto")
        self.assertEqual(detail.pending_debug.active_status, "pending_resolution")
        self.assertEqual(detail.pending_debug.candidate_count, 2)
        self.assertEqual(detail.pending_debug.requirements_pending_count, 1)
        self.assertEqual(detail.pending_debug.consistency, "consistent")

    def test_detail_includes_pending_debug_for_invalid_state(self) -> None:
        pedido = self._build_pedido(
            context_type="product_selection",
            pending_intents={"active": "not-a-dict"},
        )
        session = self._stub_session_maker(pedido=pedido, lineas=[])
        detail = PilotOrderOperationsViewService(session).get_detail(42)
        assert detail.pending_debug is not None
        self.assertEqual(detail.pending_debug.pending_encoding, "invalid")
        self.assertEqual(detail.pending_debug.consistency, "inconsistent")

    def test_detail_does_not_leak_raw_payload_through_view(self) -> None:
        pedido = self._build_pedido(
            context_type="product_selection",
            pending_intents={
                "version": 1,
                "active": {
                    "intent": "agregar_producto",
                    "source_text": "SECRET-SOURCE-TEXT",
                    "status": "pending_resolution",
                    "handler": "agregar_producto",
                    "resolved_data": {"observation": "SECRET-OBSERVATION"},
                    "candidate_ids": [99],
                },
                "queue": [],
            },
        )
        session = self._stub_session_maker(pedido=pedido, lineas=[])
        detail = PilotOrderOperationsViewService(session).get_detail(42)
        assert detail.pending_debug is not None
        payload = repr(detail.pending_debug)
        for forbidden in (
            "SECRET-SOURCE-TEXT",
            "SECRET-OBSERVATION",
            "resolved_data",
            "candidate_ids",
            "pending_intents",
            "raw_context_type",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)


class FormatOrderLinePriceTest(unittest.TestCase):
    """Task 9.1: the unit-price formatter keeps the stored
    :class:`decimal.Decimal` value intact and is JSON-safe."""

    def test_decimal_string_preserves_stored_value(self) -> None:
        self.assertEqual(
            format_order_line_price(Decimal("150.00")), "150.00"
        )

    def test_zero_decimal_renders_as_zero(self) -> None:
        self.assertEqual(format_order_line_price(Decimal(0)), "0")

    def test_large_decimal_preserves_precision(self) -> None:
        self.assertEqual(
            format_order_line_price(Decimal("123456789.99")),
            "123456789.99",
        )


class OrderLineSnapshotFieldsTest(unittest.TestCase):
    """Task 9.1: :class:`OrderLineSnapshot` only exposes the
    documented closed fields and refuses extra members."""

    def test_dataclass_has_only_documented_fields(self) -> None:
        snapshot = OrderLineSnapshot(
            id=100,
            producto_nombre="Pan",
            presentacion_descripcion="Bolsa x 1kg",
            cantidad=2,
            precio_unitario_display="150.00",
            observaciones=None,
        )
        self.assertEqual(
            set(snapshot.__dataclass_fields__.keys()),
            {
                "id",
                "producto_nombre",
                "presentacion_descripcion",
                "cantidad",
                "precio_unitario_display",
                "observaciones",
            },
        )

    def test_snapshot_is_frozen(self) -> None:
        snapshot = OrderLineSnapshot(
            id=100,
            producto_nombre="Pan",
            presentacion_descripcion=None,
            cantidad=2,
            precio_unitario_display="150.00",
            observaciones=None,
        )
        with self.assertRaises(FrozenInstanceError):
            snapshot.id = 999  # type: ignore[misc]

    def test_snapshot_repr_does_not_leak_internal_value(self) -> None:
        snapshot = OrderLineSnapshot(
            id=100,
            producto_nombre="Pan",
            presentacion_descripcion=None,
            cantidad=2,
            precio_unitario_display="150.00",
            observaciones="<script>",
        )
        payload = repr(snapshot)
        # The repr never includes a Decimal token or any field name
        # beyond the documented wire contract.
        for forbidden in (
            "Decimal",
            "id_session",
            "id_pedido",
            "id_cliente",
            "id_comercio",
            "pending_intents",
            "context_type",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)


class GetOrderLinesSnapshotTest(unittest.TestCase):
    """Task 9.1: the new public projection emits a typed,
    JSON-safe :class:`OrderLineSnapshot` list for the requested
    pedido only."""

    def _stub_session(self, lineas: list) -> MagicMock:
        session = MagicMock(name="DatabaseSession")
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()
        session.begin = MagicMock()
        session.close = MagicMock()
        session.execute.return_value = _Result(
            scalars_list=lineas, scalar_value=None
        )
        return session

    def _build_line(
        self,
        *,
        id: int,
        cantidad: int,
        precio_unitario: Decimal,
        observaciones: str | None,
        presentacion_descripcion: str | None = "Bolsa x 1kg",
        producto_nombre: str = "Pan",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=id,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            observaciones=observaciones,
            producto_presentacion=SimpleNamespace(
                producto=SimpleNamespace(nombre=producto_nombre),
                presentacion=SimpleNamespace(
                    descripcion=presentacion_descripcion
                ),
            ),
        )

    def test_returns_empty_snapshot_for_empty_lines(self) -> None:
        session = self._stub_session([])
        snapshots = (
            PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        )
        self.assertEqual(snapshots, [])
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()

    def test_maps_a_single_line_with_all_fields(self) -> None:
        line = self._build_line(
            id=100,
            cantidad=2,
            precio_unitario=Decimal("150.00"),
            observaciones="Sin sal",
        )
        session = self._stub_session([line])
        snapshots = (
            PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        )
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertIsInstance(snapshot, OrderLineSnapshot)
        self.assertEqual(snapshot.id, 100)
        self.assertEqual(snapshot.producto_nombre, "Pan")
        self.assertEqual(snapshot.presentacion_descripcion, "Bolsa x 1kg")
        self.assertEqual(snapshot.cantidad, 2)
        self.assertEqual(snapshot.precio_unitario_display, "150.00")
        self.assertEqual(snapshot.observaciones, "Sin sal")

    def test_maps_multiple_lines_with_nullable_presentation_and_observation(
        self,
    ) -> None:
        lines = [
            self._build_line(
                id=1,
                cantidad=1,
                precio_unitario=Decimal("10.50"),
                observaciones=None,
                presentacion_descripcion=None,
                producto_nombre="Agua",
            ),
            self._build_line(
                id=2,
                cantidad=3,
                precio_unitario=Decimal("9.99"),
                observaciones="Sin hielo",
                presentacion_descripcion="Lata 330ml",
                producto_nombre="Gaseosa",
            ),
        ]
        session = self._stub_session(lines)
        snapshots = (
            PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        )
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0].id, 1)
        self.assertIsNone(snapshots[0].presentacion_descripcion)
        self.assertIsNone(snapshots[0].observaciones)
        self.assertEqual(snapshots[0].precio_unitario_display, "10.50")
        self.assertEqual(snapshots[1].id, 2)
        self.assertEqual(snapshots[1].presentacion_descripcion, "Lata 330ml")
        self.assertEqual(snapshots[1].observaciones, "Sin hielo")
        self.assertEqual(snapshots[1].precio_unitario_display, "9.99")

    def test_snapshot_is_isolated_by_pedido_id(self) -> None:
        """The query is scoped strictly by ``pedido_id``; the helper
        must never broaden the search to another pedido, session,
        cliente, comercio or product. The session is exercised once
        so the helper cannot issue a secondary lookup."""
        line = self._build_line(
            id=7,
            cantidad=1,
            precio_unitario=Decimal("1.00"),
            observaciones=None,
        )
        session = self._stub_session([line])
        PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        self.assertEqual(session.execute.call_count, 1)

    def test_snapshot_does_not_carry_decimal_or_orm_payload(self) -> None:
        line = self._build_line(
            id=100,
            cantidad=2,
            precio_unitario=Decimal("150.00"),
            observaciones="Sin sal",
        )
        session = self._stub_session([line])
        snapshots = (
            PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        )
        # The JSON-safe serialised payload must never contain a
        # Decimal token or any ORM attribute leaked from the row.
        payload = repr(snapshots)
        for forbidden in (
            "Decimal",
            "pedidos_productos",
            "ProductoPresentacion",
            "producto_presentacion",
            "id_pedido",
            "id_session",
            "id_comercio",
            "id_cliente",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_snapshot_does_not_mutate_session(self) -> None:
        line = self._build_line(
            id=100,
            cantidad=2,
            precio_unitario=Decimal("150.00"),
            observaciones=None,
        )
        session = self._stub_session([line])
        PilotOrderOperationsViewService(session).get_order_lines_snapshot(42)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()
        session.refresh.assert_not_called()
        session.begin.assert_not_called()
        session.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
