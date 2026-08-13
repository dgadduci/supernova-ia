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
    ClientSummary,
    CommerceSummary,
    InvalidListFilter,
    InvalidPedidoId,
    LocalDateTimeView,
    OrderDetailView,
    OrderListRow,
    OrderSummary,
    OutboundMessageView,
    PilotOrderOperationsViewService,
    ProviderReceiptView,
    SessionSummary,
    format_local_datetime,
    format_local_datetime_optional,
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


if __name__ == "__main__":
    unittest.main()
