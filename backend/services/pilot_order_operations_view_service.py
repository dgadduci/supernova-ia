"""Read-only projection service for the pilot order operations panel.

The service renders one order row, the order detail with its session,
client, commerce, lines, payment/delivery and provider-history entries,
and the bounded list view. The router owns the read session and the
template rendering; this service never opens a transaction, never
calls ``commit`` / ``rollback`` / ``flush`` / ``refresh`` / ``begin`` /
``close``, and never mutates any row. All the values exposed here are
typed view models so the templates can rely on a stable shape and the
tests can verify the privacy and isolation boundaries without
touching SQLAlchemy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import joinedload

from backend.models import (
    EstadoPedido,
    EstadoSession,
    MensajeProveedorSaliente,
    Pedido,
    PedidoProducto,
    ProductoPresentacion,
    RecepcionMensajeProveedor,
)
from backend.models import (
    Session as SessionModel,
)

DEFAULT_PAGE_SIZE = 25
ALLOWED_PAGE_SIZES = (25, 50, 100)
MAX_PAGE_SIZE = 100
MAX_DATE_RANGE_DAYS = 31
DEFAULT_LOOKBACK_DAYS = 7
CLOSED_ORDER_STATES: tuple[EstadoPedido, ...] = (
    EstadoPedido.ENTREGADO,
    EstadoPedido.CANCELADO,
    EstadoPedido.TERMINADO,
)
FALLBACK_ZONE_LABEL = "UTC"


@dataclass(frozen=True)
class LocalDateTimeView:
    """Human-facing representation of a UTC ``datetime`` in a chosen
    ``zoneinfo`` zone.

    The original UTC instant is preserved on the parent view model;
    this dataclass only carries the rendering data (the ISO
    representation with the local UTC offset and the explicit zone
    label shown next to it). An empty or invalid zone falls back to
    ``UTC`` so the timestamp is never lost.
    """

    iso: str
    zone_label: str


def format_local_datetime(
    value: datetime,
    zona_horaria: str | None,
) -> LocalDateTimeView:
    """Convert ``value`` to the ``zona_horaria`` zone for display.

    The instant is preserved; only the human-facing representation
    changes. The conversion is purely presentational: the original
    ``datetime`` is never mutated by the panel. A missing or invalid
    zone is silently downgraded to ``UTC`` with the literal label
    ``"UTC"``. The function is pure: no I/O, no logging, no exception
    propagation. Naive ``datetime`` values are assumed UTC so callers
    never have to guess.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    zone_label, zone = _resolve_zone(zona_horaria)
    local_value = value.astimezone(zone)
    return LocalDateTimeView(
        iso=local_value.isoformat(),
        zone_label=zone_label,
    )


def format_local_datetime_optional(
    value: datetime | None,
    zona_horaria: str | None,
) -> LocalDateTimeView | None:
    """Like :func:`format_local_datetime` but returns ``None`` when
    ``value`` is ``None`` so templates can render an em dash without
    repeating the guard."""
    if value is None:
        return None
    return format_local_datetime(value, zona_horaria)


def _resolve_zone(zona_horaria: str | None) -> tuple[str, ZoneInfo]:
    if not zona_horaria or not isinstance(zona_horaria, str):
        return FALLBACK_ZONE_LABEL, ZoneInfo(FALLBACK_ZONE_LABEL)
    cleaned = zona_horaria.strip()
    if not cleaned:
        return FALLBACK_ZONE_LABEL, ZoneInfo(FALLBACK_ZONE_LABEL)
    try:
        return cleaned, ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        return FALLBACK_ZONE_LABEL, ZoneInfo(FALLBACK_ZONE_LABEL)


@dataclass(frozen=True)
class CommerceSummary:
    id: int
    nombre_fantasia: str
    nombre_corto: str
    zona_horaria: str


@dataclass(frozen=True)
class ClientSummary:
    id: int
    nombre: str | None
    whatsapp: str
    activo: bool


@dataclass(frozen=True)
class SessionSummary:
    id: int
    estado_session: EstadoSession
    datetime_inicio: datetime
    datetime_inicio_local: LocalDateTimeView | None
    datetime_ultimo_movimiento: datetime
    datetime_ultimo_movimiento_local: LocalDateTimeView | None


@dataclass(frozen=True)
class OrderSummary:
    id: int
    estado_pedido: EstadoPedido
    fecha_alta: datetime
    fecha_alta_local: LocalDateTimeView
    fecha_ultima_modificacion: datetime
    fecha_ultima_modificacion_local: LocalDateTimeView


@dataclass(frozen=True)
class OrderLineView:
    id: int
    producto_nombre: str
    presentacion_descripcion: str | None
    cantidad: int
    precio_unitario: Decimal
    observaciones: str | None


@dataclass(frozen=True)
class PaymentMethodView:
    id: int
    descripcion: str


@dataclass(frozen=True)
class DeliveryMethodView:
    id: int
    descripcion: str


@dataclass(frozen=True)
class OrderDetailView:
    pedido: OrderSummary
    session: SessionSummary
    client: ClientSummary
    commerce: CommerceSummary
    direccion_entrega: str | None
    observaciones: str | None
    datetime_entrega_programada: datetime | None
    datetime_entrega_programada_local: LocalDateTimeView | None
    medio_pago: PaymentMethodView | None
    metodo_entrega: DeliveryMethodView | None
    lineas: list[OrderLineView] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderReceiptView:
    id: int
    fecha_recepcion: datetime
    fecha_recepcion_local: LocalDateTimeView
    proveedor: str
    canal_id: int


@dataclass(frozen=True)
class OutboundMessageView:
    id: int
    sequence: int
    fecha_creacion: datetime
    fecha_creacion_local: LocalDateTimeView
    cuerpo: str
    estado: str
    intentos: int
    estado_proveedor: str | None
    estado_proveedor_en: datetime | None
    estado_proveedor_en_local: LocalDateTimeView | None
    categoria_ultimo_fallo: str | None
    codigo_ultimo_fallo: str | None


@dataclass(frozen=True)
class ProviderHistoryEntry:
    receipt: ProviderReceiptView
    outbounds: list[OutboundMessageView]


@dataclass(frozen=True)
class ProviderHistoryView:
    cliente_id: int
    comercio_id: int
    entries: list[ProviderHistoryEntry]


@dataclass(frozen=True)
class OrderListRow:
    pedido: OrderSummary
    session: SessionSummary
    commerce: CommerceSummary
    client: ClientSummary


@dataclass(frozen=True)
class OrderListView:
    rows: list[OrderListRow]
    total: int
    page: int
    page_size: int


class PilotOrderOperationsViewError(ValueError):
    """Base class for view-layer validation errors."""


class InvalidListFilter(PilotOrderOperationsViewError):
    """Raised when the list filter parameters are malformed."""


class InvalidPedidoId(PilotOrderOperationsViewError):
    """Raised when ``pedido_id`` is not a positive integer."""


@dataclass(frozen=True)
class ListFilters:
    from_date: date
    to_date: date
    from_dt: datetime
    to_dt: datetime
    comercio_id: int | None
    estado: EstadoPedido | None
    page: int
    page_size: int


def _parse_iso_date(value: str | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidListFilter(
            f"{field_name} must be an ISO date (YYYY-MM-DD)"
        ) from exc


def _parse_page_size(value: str | None) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidListFilter(
            "page_size must be 25, 50 or 100"
        ) from exc
    if parsed not in ALLOWED_PAGE_SIZES:
        raise InvalidListFilter("page_size must be 25, 50 or 100")
    return parsed


def _parse_page(value: str | None) -> int:
    if value is None:
        return 1
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidListFilter("page must be a positive integer") from exc
    if parsed < 1:
        raise InvalidListFilter("page must be a positive integer")
    return parsed


def _parse_comercio_id(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidListFilter("comercio_id must be a positive integer") from exc
    if parsed < 1:
        raise InvalidListFilter("comercio_id must be a positive integer")
    return parsed


def _parse_estado(value: str | None) -> EstadoPedido | None:
    if value is None or value == "":
        return None
    try:
        return EstadoPedido(value)
    except ValueError as exc:
        raise InvalidListFilter(
            "estado must be one of the documented EstadoPedido values"
        ) from exc


def parse_list_filters(
    *,
    raw_from: str | None,
    raw_to: str | None,
    raw_comercio_id: str | None,
    raw_estado: str | None,
    raw_page: str | None,
    raw_page_size: str | None,
    now: datetime | None = None,
) -> ListFilters:
    """Validate and normalize the list-view query parameters.

    Returns a :class:`ListFilters` value ready to hand to
    :meth:`PilotOrderOperationsViewService.list_orders`. The caller
    receives a precise validation error on malformed input and never
    sees a query.
    """
    from_date = _parse_iso_date(raw_from, field_name="from")
    to_date = _parse_iso_date(raw_to, field_name="to")
    comercio_id = _parse_comercio_id(raw_comercio_id)
    estado = _parse_estado(raw_estado)
    page = _parse_page(raw_page)
    page_size = _parse_page_size(raw_page_size)

    reference_now = now or datetime.now(tz=timezone.utc)
    if to_date is None:
        to_date = reference_now.date()
    if from_date is None:
        from_date = to_date - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1)
    if from_date > to_date:
        raise InvalidListFilter("from must be on or before to")
    if (to_date - from_date).days + 1 > MAX_DATE_RANGE_DAYS:
        raise InvalidListFilter(
            f"from/to range must be at most {MAX_DATE_RANGE_DAYS} days"
        )

    from_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
    to_dt = datetime.combine(
        to_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )

    return ListFilters(
        from_date=from_date,
        to_date=to_date,
        from_dt=from_dt,
        to_dt=to_dt,
        comercio_id=comercio_id,
        estado=estado,
        page=page,
        page_size=page_size,
    )


def parse_pedido_id(raw_value: str) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise InvalidPedidoId("pedido_id must be a positive integer") from exc
    if parsed < 1:
        raise InvalidPedidoId("pedido_id must be a positive integer")
    return parsed


class PilotOrderOperationsViewService:
    """Read-only projection over Pedido, Session, Client, Commerce,
    PedidoProducto, MediosPago, MetodosEntrega and the
    RecepcionMensajeProveedor / MensajeProveedorSaliente history."""

    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def list_orders(self, filters: ListFilters) -> OrderListView:
        stmt = (
            select(Pedido)
            .join(SessionModel, SessionModel.id == Pedido.id_session)
            .options(
                joinedload(Pedido.session).joinedload(SessionModel.cliente),
                joinedload(Pedido.session).joinedload(SessionModel.comercio),
            )
            .where(Pedido.fecha_alta >= filters.from_dt)
            .where(Pedido.fecha_alta < filters.to_dt)
            .order_by(Pedido.fecha_alta.desc(), Pedido.id.desc())
        )
        if filters.comercio_id is not None:
            stmt = stmt.where(SessionModel.id_comercio == filters.comercio_id)
        if filters.estado is not None:
            stmt = stmt.where(Pedido.estado_pedido == filters.estado)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self._session.execute(total_stmt).scalar_one())

        offset = (filters.page - 1) * filters.page_size
        stmt = stmt.offset(offset).limit(filters.page_size)
        pedidos = list(self._session.execute(stmt).unique().scalars().all())

        rows = [self._row_from_pedido(pedido) for pedido in pedidos]
        return OrderListView(
            rows=rows,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
        )

    def get_detail(self, pedido_id: int) -> OrderDetailView | None:
        stmt = (
            select(Pedido)
            .where(Pedido.id == pedido_id)
            .options(
                joinedload(Pedido.session).joinedload(SessionModel.cliente),
                joinedload(Pedido.session).joinedload(SessionModel.comercio),
                joinedload(Pedido.medio_pago),
                joinedload(Pedido.metodo_entrega),
            )
        )
        pedido = self._session.execute(stmt).unique().scalar_one_or_none()
        if pedido is None:
            return None

        lineas = self._list_lineas(pedido_id)
        medio_pago = self._medio_pago_view(pedido)
        metodo_entrega = self._metodo_entrega_view(pedido)
        zona_horaria = pedido.session.comercio.zona_horaria
        return OrderDetailView(
            pedido=OrderSummary(
                id=pedido.id,
                estado_pedido=pedido.estado_pedido,
                fecha_alta=pedido.fecha_alta,
                fecha_alta_local=format_local_datetime(
                    pedido.fecha_alta, zona_horaria
                ),
                fecha_ultima_modificacion=pedido.fecha_ultima_modificacion,
                fecha_ultima_modificacion_local=format_local_datetime(
                    pedido.fecha_ultima_modificacion, zona_horaria
                ),
            ),
            session=SessionSummary(
                id=pedido.session.id,
                estado_session=pedido.session.estado_session,
                datetime_inicio=pedido.session.datetime_inicio,
                datetime_inicio_local=format_local_datetime(
                    pedido.session.datetime_inicio, zona_horaria
                ),
                datetime_ultimo_movimiento=pedido.session.datetime_ultimo_movimiento,
                datetime_ultimo_movimiento_local=format_local_datetime(
                    pedido.session.datetime_ultimo_movimiento, zona_horaria
                ),
            ),
            client=ClientSummary(
                id=pedido.session.cliente.id,
                nombre=pedido.session.cliente.nombre,
                whatsapp=pedido.session.cliente.whatsapp,
                activo=pedido.session.cliente.activo,
            ),
            commerce=CommerceSummary(
                id=pedido.session.comercio.id,
                nombre_fantasia=pedido.session.comercio.nombre_fantasia,
                nombre_corto=pedido.session.comercio.nombre_corto,
                zona_horaria=zona_horaria,
            ),
            direccion_entrega=pedido.direccion_entrega,
            observaciones=pedido.observaciones,
            datetime_entrega_programada=pedido.datetime_entrega_programada,
            datetime_entrega_programada_local=format_local_datetime_optional(
                pedido.datetime_entrega_programada, zona_horaria
            ),
            medio_pago=medio_pago,
            metodo_entrega=metodo_entrega,
            lineas=lineas,
        )

    def get_provider_history(
        self,
        *,
        cliente_id: int,
        comercio_id: int,
        zona_horaria: str | None = None,
    ) -> ProviderHistoryView:
        receipt_stmt = (
            select(RecepcionMensajeProveedor)
            .where(RecepcionMensajeProveedor.cliente_id == cliente_id)
            .where(RecepcionMensajeProveedor.comercio_id == comercio_id)
            .order_by(
                RecepcionMensajeProveedor.fecha_recepcion.asc(),
                RecepcionMensajeProveedor.id.asc(),
            )
        )
        receipts = list(
            self._session.execute(receipt_stmt).scalars().all()
        )

        outbounds: list[MensajeProveedorSaliente] = []
        if receipts:
            outbound_stmt = (
                select(MensajeProveedorSaliente)
                .where(MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    [receipt.id for receipt in receipts]
                ))
                .order_by(
                    MensajeProveedorSaliente.fecha_creacion.asc(),
                    MensajeProveedorSaliente.sequence.asc(),
                )
            )
            outbounds = list(
                self._session.execute(outbound_stmt).scalars().all()
            )
        outbounds_by_receipt: dict[int, list[OutboundMessageView]] = {}
        for outbound in outbounds:
            outbounds_by_receipt.setdefault(
                outbound.recepcion_mensaje_proveedor_id, []
            ).append(
                OutboundMessageView(
                    id=outbound.id,
                    sequence=outbound.sequence,
                    fecha_creacion=outbound.fecha_creacion,
                    fecha_creacion_local=format_local_datetime(
                        outbound.fecha_creacion, zona_horaria
                    ),
                    cuerpo=outbound.cuerpo,
                    estado=outbound.estado,
                    intentos=outbound.intentos,
                    estado_proveedor=outbound.estado_proveedor,
                    estado_proveedor_en=outbound.estado_proveedor_en,
                    estado_proveedor_en_local=format_local_datetime_optional(
                        outbound.estado_proveedor_en, zona_horaria
                    ),
                    categoria_ultimo_fallo=outbound.categoria_ultimo_fallo,
                    codigo_ultimo_fallo=outbound.codigo_ultimo_fallo,
                )
            )

        entries = [
            ProviderHistoryEntry(
                receipt=ProviderReceiptView(
                    id=receipt.id,
                    fecha_recepcion=receipt.fecha_recepcion,
                    fecha_recepcion_local=format_local_datetime(
                        receipt.fecha_recepcion, zona_horaria
                    ),
                    proveedor=receipt.proveedor,
                    canal_id=receipt.canal_id,
                ),
                outbounds=outbounds_by_receipt.get(receipt.id, []),
            )
            for receipt in receipts
        ]

        return ProviderHistoryView(
            cliente_id=cliente_id,
            comercio_id=comercio_id,
            entries=entries,
        )

    def _row_from_pedido(self, pedido: Pedido) -> OrderListRow:
        session = pedido.session
        zona_horaria = session.comercio.zona_horaria
        return OrderListRow(
            pedido=OrderSummary(
                id=pedido.id,
                estado_pedido=pedido.estado_pedido,
                fecha_alta=pedido.fecha_alta,
                fecha_alta_local=format_local_datetime(
                    pedido.fecha_alta, zona_horaria
                ),
                fecha_ultima_modificacion=pedido.fecha_ultima_modificacion,
                fecha_ultima_modificacion_local=format_local_datetime(
                    pedido.fecha_ultima_modificacion, zona_horaria
                ),
            ),
            session=SessionSummary(
                id=session.id,
                estado_session=session.estado_session,
                datetime_inicio=session.datetime_inicio,
                datetime_inicio_local=format_local_datetime(
                    session.datetime_inicio, zona_horaria
                ),
                datetime_ultimo_movimiento=session.datetime_ultimo_movimiento,
                datetime_ultimo_movimiento_local=format_local_datetime(
                    session.datetime_ultimo_movimiento, zona_horaria
                ),
            ),
            commerce=CommerceSummary(
                id=session.comercio.id,
                nombre_fantasia=session.comercio.nombre_fantasia,
                nombre_corto=session.comercio.nombre_corto,
                zona_horaria=zona_horaria,
            ),
            client=ClientSummary(
                id=session.cliente.id,
                nombre=session.cliente.nombre,
                whatsapp=session.cliente.whatsapp,
                activo=session.cliente.activo,
            ),
        )

    def _list_lineas(self, pedido_id: int) -> list[OrderLineView]:
        stmt = (
            select(PedidoProducto)
            .where(PedidoProducto.id_pedido == pedido_id)
            .options(
                joinedload(PedidoProducto.producto_presentacion)
                .joinedload(ProductoPresentacion.producto),
                joinedload(PedidoProducto.producto_presentacion)
                .joinedload(ProductoPresentacion.presentacion),
            )
            .order_by(PedidoProducto.id.asc())
        )
        rows = list(self._session.execute(stmt).unique().scalars().all())
        lineas: list[OrderLineView] = []
        for row in rows:
            presentacion = row.producto_presentacion
            producto = presentacion.producto if presentacion is not None else None
            presentacion_obj = (
                presentacion.presentacion if presentacion is not None else None
            )
            descripcion = (
                presentacion_obj.descripcion
                if presentacion_obj is not None
                else None
            )
            lineas.append(
                OrderLineView(
                    id=row.id,
                    producto_nombre=producto.nombre if producto is not None else "",
                    presentacion_descripcion=descripcion,
                    cantidad=row.cantidad,
                    precio_unitario=row.precio_unitario,
                    observaciones=row.observaciones,
                )
            )
        return lineas

    @staticmethod
    def _medio_pago_view(pedido: Pedido) -> PaymentMethodView | None:
        medio = pedido.medio_pago
        if medio is None:
            return None
        return PaymentMethodView(id=medio.id, descripcion=medio.descripcion)

    @staticmethod
    def _metodo_entrega_view(pedido: Pedido) -> DeliveryMethodView | None:
        metodo = pedido.metodo_entrega
        if metodo is None:
            return None
        return DeliveryMethodView(
            id=metodo.id, descripcion=metodo.descripcion
        )


__all__ = [
    "ALLOWED_PAGE_SIZES",
    "CLOSED_ORDER_STATES",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_PAGE_SIZE",
    "FALLBACK_ZONE_LABEL",
    "MAX_DATE_RANGE_DAYS",
    "MAX_PAGE_SIZE",
    "ClientSummary",
    "CommerceSummary",
    "DeliveryMethodView",
    "InvalidListFilter",
    "InvalidPedidoId",
    "ListFilters",
    "LocalDateTimeView",
    "OrderDetailView",
    "OrderLineView",
    "OrderListRow",
    "OrderListView",
    "OrderSummary",
    "OutboundMessageView",
    "PaymentMethodView",
    "PilotOrderOperationsViewError",
    "PilotOrderOperationsViewService",
    "ProviderHistoryEntry",
    "ProviderHistoryView",
    "ProviderReceiptView",
    "SessionSummary",
    "format_local_datetime",
    "format_local_datetime_optional",
    "parse_list_filters",
    "parse_pedido_id",
]
