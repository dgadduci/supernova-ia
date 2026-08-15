from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import joinedload

from backend.models import (
    Pedido,
    PedidoProducto,
    Precio,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.services.exceptions import PedidoProductoNotFound


class PedidoProductoRepository:
    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def get(self, item_id: int) -> PedidoProducto | None:
        return self._session.get(PedidoProducto, item_id)

    def list_by_pedido(self, pedido_id: int) -> list[PedidoProducto]:
        stmt = (
            select(PedidoProducto)
            .options(
                joinedload(PedidoProducto.producto_presentacion)
                .joinedload(ProductoPresentacion.producto)
                .joinedload(Producto.categoria),
                joinedload(PedidoProducto.producto_presentacion)
                .joinedload(ProductoPresentacion.presentacion),
            )
            .where(PedidoProducto.id_pedido == pedido_id)
            .order_by(PedidoProducto.id)
        )
        return list(self._session.execute(stmt).scalars().unique())

    def get_for_pedido(
        self,
        pedido_id: int,
        pedido_producto_id: int,
    ) -> PedidoProducto | None:
        item = self._session.get(PedidoProducto, pedido_producto_id)
        if item is None:
            return None
        if item.id_pedido != pedido_id:
            return None
        return item

    def get_by_pedido_and_producto_presentacion(
        self,
        pedido_id: int,
        id_producto_presentacion: int,
    ) -> PedidoProducto | None:
        stmt = select(PedidoProducto).where(
            PedidoProducto.id_pedido == pedido_id,
            PedidoProducto.id_producto_presentacion == id_producto_presentacion,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def pedido(self, pedido_id: int) -> Pedido | None:
        return self._session.get(Pedido, pedido_id)

    def session(self, session_id: int) -> SessionModel | None:
        """Return the ``Session`` row for ``session_id`` or
        ``None`` when no row exists.

        Used by the modern ``agregar_producto`` seam to validate
        that the conversation session exists and is in
        ``EstadoSession.ACTIVA`` before staging a price-snapshotted
        line. The repository never calls ``commit`` / ``rollback``
        / ``flush`` / ``refresh`` / ``begin`` / ``close`` /
        ``expire``; the caller's outer transaction remains the only
        owner of full-turn atomicity.
        """
        return self._session.get(SessionModel, session_id)

    def producto_presentacion_exists(self, id_producto_presentacion: int) -> bool:
        return self._session.get(ProductoPresentacion, id_producto_presentacion) is not None

    def current_precio(self, id_producto_presentacion: int) -> Precio | None:
        stmt = select(Precio).where(Precio.id_producto_presentacion == id_producto_presentacion)
        return self._session.execute(stmt).scalar_one_or_none()

    def current_precio_count(self, id_producto_presentacion: int) -> int:
        """Return the number of ``Precio`` rows for the given
        ``ProductoPresentacion``.

        Used by the modern ``agregar_producto`` seam to require
        *exactly one* current price before staging a price-snapshotted
        line. The count is computed via ``select(Precio)`` so it never
        triggers an ORM flush, and the helper never calls
        ``commit`` / ``rollback`` / ``flush`` / ``refresh`` / ``begin``
        / ``close``; the caller's outer transaction remains the only
        owner of atomicity.
        """
        stmt = select(Precio).where(
            Precio.id_producto_presentacion == id_producto_presentacion
        )
        return len(list(self._session.execute(stmt).scalars().all()))

    def stage_increment_existing_line(
        self,
        pedido_id: int,
        id_producto_presentacion: int,
        cantidad: int,
    ) -> PedidoProducto | None:
        """Increment an existing ``PedidoProducto`` row in place
        without owning transaction control.

        Returns the staged row, or ``None`` when no line exists yet
        for ``(pedido_id, id_producto_presentacion)``. The repository
        never calls ``commit`` / ``rollback`` / ``flush`` /
        ``refresh`` / ``expire`` / ``begin`` / ``close``; the
        caller's outer transaction is the only owner of the full-turn
        atomicity guarantee. The repository never reads the commerce
        catalog and never inspects the session's pedidos beyond the
        single row fetch.
        """
        existing = self.get_by_pedido_and_producto_presentacion(
            pedido_id, id_producto_presentacion
        )
        if existing is None:
            return None
        existing.cantidad = existing.cantidad + cantidad
        return existing

    def stage_create_with_price_snapshot_no_flush(
        self,
        *,
        id_pedido: int,
        id_producto_presentacion: int,
        cantidad: int,
        precio_unitario: Decimal,
    ) -> PedidoProducto:
        """Stage a new ``PedidoProducto`` row with a price snapshot
        without owning transaction control.

        The repository performs only ``session.add(row)`` so the
        caller's outer transaction remains the only owner of the
        full-turn atomicity guarantee. The repository never calls
        ``commit`` / ``rollback`` / ``flush`` / ``refresh`` /
        ``expire`` / ``begin`` / ``close``; the row identifier is
        assigned by the database when the caller commits. The
        repository never reads the commerce catalog and never
        inspects the session's pedidos beyond the single insert.
        """
        row = PedidoProducto(
            id_pedido=id_pedido,
            id_producto_presentacion=id_producto_presentacion,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            observaciones=None,
        )
        self._session.add(row)
        return row

    def create(
        self,
        id_pedido: int,
        id_producto_presentacion: int,
        cantidad: int,
        precio_unitario: Decimal,
        observaciones: str | None,
    ) -> PedidoProducto:
        row = PedidoProducto(
            id_pedido=id_pedido,
            id_producto_presentacion=id_producto_presentacion,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            observaciones=observaciones,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update(
        self,
        item: PedidoProducto,
        cantidad: int | None,
        observaciones: str | None,
    ) -> PedidoProducto:
        if cantidad is not None:
            item.cantidad = cantidad
        if observaciones is not None:
            item.observaciones = observaciones
        self._session.flush()
        return item

    def delete(self, item: PedidoProducto) -> None:
        self._session.delete(item)
        self._session.flush()

    def delete_all_by_pedido(self, pedido_id: int) -> list[PedidoProducto]:
        """Stage deletion of every ``PedidoProducto`` row for the given pedido.

        Returns the deleted rows so the caller can report the count. The
        repository never commits, rolls back, refreshes, or begins a
        transaction; it only stages ``delete`` plus ``flush`` so the caller's
        outer transaction owns the atomicity guarantee. The caller MUST
        re-validate the pedido state and ownership before invoking this
        helper.
        """
        rows = self.list_by_pedido(pedido_id)
        for row in rows:
            self._session.delete(row)
        if rows:
            self._session.flush()
        return list(rows)

    def decrement(self, pedido_producto_id: int, cantidad: int) -> PedidoProducto:
        item = self._session.get(PedidoProducto, pedido_producto_id)
        if item is None:
            raise PedidoProductoNotFound(pedido_producto_id)
        item.cantidad = item.cantidad - cantidad
        self._session.flush()
        return item

    def increment(self, pedido_producto_id: int, cantidad: int) -> PedidoProducto:
        item = self._session.get(PedidoProducto, pedido_producto_id)
        if item is None:
            raise PedidoProductoNotFound(pedido_producto_id)
        item.cantidad = item.cantidad + cantidad
        self._session.flush()
        return item

    def create_with_price_snapshot(
        self,
        id_pedido: int,
        id_producto_presentacion: int,
        cantidad: int,
        precio_unitario: Decimal,
    ) -> PedidoProducto:
        row = PedidoProducto(
            id_pedido=id_pedido,
            id_producto_presentacion=id_producto_presentacion,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            observaciones=None,
        )
        self._session.add(row)
        self._session.flush()
        return row