from sqlalchemy.orm import Session as SqlSession

from backend.models import (
    EstadoPedido,
    PedidoProducto,
    ProductoPresentacion,
)
from backend.models.session import EstadoSession
from backend.repositories.pedido_producto_repository import PedidoProductoRepository
from backend.services.exceptions import (
    InvalidCantidad,
    PedidoNotFound,
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
    PedidoSessionMismatch,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)
from backend.services.modification_result import ModificationResult
from backend.services.product_add_result import (
    REJECTED_INVALID_INPUT,
    REJECTED_MISSING_PRESENTATION,
    REJECTED_NOT_EDITABLE,
    REJECTED_PRICE_UNAVAILABLE,
    REJECTED_SESSION_OR_PEDIDO,
    STATUS_EXECUTED,
    STATUS_REJECTED,
    ProductAddResult,
)


def _trim_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class PedidoProductoService:
    def __init__(self, session: SqlSession) -> None:
        self._session = session
        self._repo = PedidoProductoRepository(session)

    def get_by_id(self, item_id: int) -> PedidoProducto:
        item = self._repo.get(item_id)
        if item is None:
            raise PedidoProductoNotFound(item_id)
        return item

    def list_by_pedido(self, pedido_id: int) -> list[PedidoProducto]:
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        return self._repo.list_by_pedido(pedido_id)

    def get_for_pedido(
        self,
        pedido_id: int,
        pedido_producto_id: int,
    ) -> PedidoProducto:
        item = self._repo.get_for_pedido(pedido_id, pedido_producto_id)
        if item is None:
            raise PedidoProductoNotFound(pedido_producto_id)
        return item

    def add_or_increment(
        self,
        pedido_id: int,
        id_producto_presentacion: int,
        cantidad: int,
        observaciones: str | None,
    ) -> PedidoProducto:
        if cantidad <= 0:
            raise InvalidCantidad(cantidad)
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(pedido_id, pedido.estado_pedido.value)
        if not self._repo.producto_presentacion_exists(id_producto_presentacion):
            raise ProductoPresentacionNotFound(id_producto_presentacion)
        cleaned_observaciones = _trim_to_none(observaciones)
        existing = self._repo.get_by_pedido_and_producto_presentacion(
            pedido_id, id_producto_presentacion
        )
        if existing is not None:
            existing.cantidad = existing.cantidad + cantidad
            try:
                self._session.flush()
                self._session.commit()
                self._session.refresh(existing)
            except Exception:
                self._session.rollback()
                raise
            return existing
        precio = self._repo.current_precio(id_producto_presentacion)
        if precio is None:
            raise PrecioNotFound(id_producto_presentacion)
        try:
            row = self._repo.create(
                id_pedido=pedido_id,
                id_producto_presentacion=id_producto_presentacion,
                cantidad=cantidad,
                precio_unitario=precio.precio,
                observaciones=cleaned_observaciones,
            )
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def add(
        self,
        pedido_id: int,
        id_producto_presentacion: int,
        cantidad: int,
        observaciones: str | None,
    ) -> PedidoProducto:
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(pedido_id, pedido.estado_pedido.value)
        if not self._repo.producto_presentacion_exists(id_producto_presentacion):
            raise ProductoPresentacionNotFound(id_producto_presentacion)
        precio = self._repo.current_precio(id_producto_presentacion)
        if precio is None:
            raise PrecioNotFound(id_producto_presentacion)
        cleaned_observaciones = _trim_to_none(observaciones)
        try:
            row = self._repo.create(
                id_pedido=pedido_id,
                id_producto_presentacion=id_producto_presentacion,
                cantidad=cantidad,
                precio_unitario=precio.precio,
                observaciones=cleaned_observaciones,
            )
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def update(
        self,
        item_id: int,
        cantidad: int | None,
        observaciones: str | None,
    ) -> PedidoProducto:
        item = self._repo.get(item_id)
        if item is None:
            raise PedidoProductoNotFound(item_id)
        pedido = self._repo.pedido(item.id_pedido)
        if pedido is None:
            raise PedidoNotFound(item.id_pedido)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(item.id_pedido, pedido.estado_pedido.value)
        cleaned_observaciones = _trim_to_none(observaciones) if observaciones is not None else None
        try:
            row = self._repo.update(item, cantidad, cleaned_observaciones)
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def delete(self, item_id: int) -> None:
        item = self._repo.get(item_id)
        if item is None:
            raise PedidoProductoNotFound(item_id)
        pedido = self._repo.pedido(item.id_pedido)
        if pedido is None:
            raise PedidoNotFound(item.id_pedido)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(item.id_pedido, pedido.estado_pedido.value)
        try:
            self._repo.delete(item)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def clear_pedido_lines(self, pedido_id: int) -> int:
        """Atomically delete every ``PedidoProducto`` row for the given pedido.

        This is the transaction-neutral all-lines clear operation for
        ``vaciar_pedido``. The method validates the pedido state, then
        delegates to ``PedidoProductoRepository.delete_all_by_pedido`` which
        stages every deletion in the caller's transaction. The service
        NEVER calls ``commit``, ``rollback``, ``flush``, ``refresh``,
        ``begin``, ``expire``, or ``close``; the outer transactional
        processor owns the full-turn atomicity guarantee.

        Raises:
            PedidoNotFound: when no pedido exists with the given id.
            PedidoProductoNotEditable: when the pedido is not in
                ``borrador`` state.

        Returns:
            The number of ``PedidoProducto`` rows staged for deletion.
        """
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(
                pedido_id, pedido.estado_pedido.value
            )
        deleted = self._repo.delete_all_by_pedido(pedido_id)
        return len(deleted)

    def stage_add_or_increment_for_session(
        self,
        *,
        session_id: int,
        pedido_id: int,
        id_producto_presentacion: int,
        cantidad: int,
    ) -> ProductAddResult:
        """Stage a single create or increment for the modern
        ``agregar_producto`` provider turn.

        This is the dedicated caller-owned seam used only by the
        modern ``agregar_producto`` handler. It validates, in order:

        1. ``cantidad`` is a positive integer (not a ``bool``) — maps
           to :data:`REJECTED_INVALID_INPUT`.
        2. ``id_producto_presentacion`` is a positive integer — maps
           to :data:`REJECTED_INVALID_INPUT`.
        3. The ``Session`` exists for ``session_id`` and is in
           ``EstadoSession.ACTIVA`` — maps to
           :data:`REJECTED_SESSION_OR_PEDIDO`.
        4. ``Pedido`` exists for ``pedido_id`` and
           ``Pedido.id_session`` equals ``session_id`` — maps to
           :data:`REJECTED_SESSION_OR_PEDIDO`.
        5. ``Pedido.estado_pedido == BORRADOR`` — maps to
           :data:`REJECTED_NOT_EDITABLE`.
        6. ``ProductoPresentacion`` exists for
           ``id_producto_presentacion`` — maps to
           :data:`REJECTED_MISSING_PRESENTATION`.
        7. The presentation has exactly one current ``Precio`` — maps
           to :data:`REJECTED_PRICE_UNAVAILABLE` (zero or multiple).

        Only when every guard passes does the service stage either
        an existing-line increment or a new price-snapshotted line
        through :class:`PedidoProductoRepository` and return a
        :class:`ProductAddResult` whose ``status`` is
        :data:`STATUS_EXECUTED`.

        The service NEVER calls ``commit``, ``rollback``, ``flush``,
        ``refresh``, ``expire``, ``begin``, or ``close``; the outer
        transactional processor owns the full-turn atomicity
        guarantee. The service NEVER selects a presentation outside
        the resolved candidate set and NEVER infers a price from any
        fallback. Unexpected technical failures propagate so the
        caller can roll back.
        """
        if (
            isinstance(cantidad, bool)
            or not isinstance(cantidad, int)
            or cantidad <= 0
        ):
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_INVALID_INPUT
            )
        if (
            isinstance(id_producto_presentacion, bool)
            or not isinstance(id_producto_presentacion, int)
            or id_producto_presentacion <= 0
        ):
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_INVALID_INPUT
            )

        session = self._repo.session(session_id)
        if session is None or session.estado_session != EstadoSession.ACTIVA:
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_SESSION_OR_PEDIDO
            )

        pedido = self._repo.pedido(pedido_id)
        if pedido is None or int(pedido.id_session) != int(session_id):
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_SESSION_OR_PEDIDO
            )
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_NOT_EDITABLE
            )

        if not self._repo.producto_presentacion_exists(
            id_producto_presentacion
        ):
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_MISSING_PRESENTATION
            )

        precio_count = self._repo.current_precio_count(
            id_producto_presentacion
        )
        if precio_count != 1:
            return ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_PRICE_UNAVAILABLE
            )
        precio = self._repo.current_precio(id_producto_presentacion)
        assert precio is not None

        existing = self._repo.stage_increment_existing_line(
            pedido_id=pedido_id,
            id_producto_presentacion=id_producto_presentacion,
            cantidad=cantidad,
        )
        if existing is not None:
            return ProductAddResult(
                status=STATUS_EXECUTED,
                linea_creada=False,
                cantidad_final=int(existing.cantidad),
                precio_unitario=precio.precio,
            )
        self._repo.stage_create_with_price_snapshot_no_flush(
            id_pedido=pedido_id,
            id_producto_presentacion=id_producto_presentacion,
            cantidad=cantidad,
            precio_unitario=precio.precio,
        )
        return ProductAddResult(
            status=STATUS_EXECUTED,
            linea_creada=True,
            cantidad_final=cantidad,
            precio_unitario=precio.precio,
        )

    def set_observacion_producto(
        self,
        *,
        session_id: int,
        pedido_id: int,
        pedido_producto_id: int,
        observacion: str | None,
    ) -> PedidoProducto:
        """Assign a nullable ``observaciones`` value to a single line of an
        active conversation session's own ``borrador`` pedido.

        The caller-owned transaction seam validates, in order:

        1. the ``Pedido`` exists for ``pedido_id``;
        2. ``Pedido.id_session`` equals ``session_id``;
        3. ``Pedido.estado_pedido == BORRADOR``;
        4. the ``PedidoProducto`` exists and belongs to that pedido.

        Only then does the service stage the assignment through
        ``PedidoProductoRepository.set_observacion``. The service NEVER
        calls ``commit``, ``rollback``, ``flush``, ``refresh``, ``expire``,
        ``begin``, or ``close``; the outer transactional processor owns
        the full-turn atomicity guarantee. ``observacion`` is stored as
        supplied (``None`` clears the column); the caller is responsible
        for trimming set values before invoking this method.

        Raises:
            PedidoNotFound: when no pedido exists for ``pedido_id``.
            PedidoSessionMismatch: when ``Pedido.id_session`` differs from
                ``session_id``.
            PedidoProductoNotEditable: when the pedido is not in
                ``borrador`` state.
            PedidoProductoNotFound: when the line does not exist or does
                not belong to ``pedido_id``.

        Returns:
            The staged ``PedidoProducto`` row with its ``observaciones``
            attribute updated. The actual persistence is performed by the
            caller's outer transaction.
        """
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        if int(pedido.id_session) != int(session_id):
            raise PedidoSessionMismatch(pedido_id, int(session_id))
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoProductoNotEditable(
                pedido_id, pedido.estado_pedido.value
            )
        line = self._repo.set_observacion(
            pedido_id=pedido_id,
            pedido_producto_id=pedido_producto_id,
            observacion=observacion,
        )
        if line is None:
            raise PedidoProductoNotFound(pedido_producto_id)
        return line

    @staticmethod
    def _resolve_cantidad_a_modificar(
        explicit_cantidad: int | None,
        source_cantidad: int,
    ) -> int | None:
        """Return `cantidad_a_modificar` from the explicit argument or the
        current source-line quantity.

        This is the single authoritative place that derives the transfer
        quantity for `modificar_producto`. It NEVER substitutes `1` for an
        omitted quantity; an explicit `None` input means the full current
        source quantity is transferred.

        Returns `None` when the explicit argument is not a positive integer
        (so the caller can emit the deterministic `invalid_quantity`
        reason).
        """
        if explicit_cantidad is None:
            return source_cantidad
        if isinstance(explicit_cantidad, bool) or not isinstance(
            explicit_cantidad, int
        ):
            return None
        if explicit_cantidad <= 0:
            return None
        return explicit_cantidad

    @staticmethod
    def _resolve_cantidad_destino(
        explicit_cantidad_destino: int | None,
        effective_source_cantidad: int,
    ) -> int | None:
        """Return the authoritative destination quantity.

        When the caller supplies an explicit positive destination
        quantity, that value is returned verbatim so the destination can
        differ from the source quantity. Otherwise (legacy path) the
        destination mirrors the effective source quantity, preserving the
        existing equal-quantity contract.

        Returns `None` only when the explicit value is present but
        non-positive or non-integer so the caller can emit the
        deterministic `invalid_quantity` reason.
        """
        if explicit_cantidad_destino is None:
            return effective_source_cantidad
        if (
            isinstance(explicit_cantidad_destino, bool)
            or not isinstance(explicit_cantidad_destino, int)
        ):
            return None
        if explicit_cantidad_destino <= 0:
            return None
        return explicit_cantidad_destino

    def modify_product(
        self,
        pedido_id: int,
        pedido_producto_origen_id: int,
        producto_presentacion_destino_id: int,
        cantidad: int | None,
        cantidad_destino: int | None = None,
    ) -> ModificationResult:
        """Atomically replace the source line with the destination product.

        The service performs every required validation before mutating any
        row, then executes the source update (decrement or delete) and the
        destination update (create or increment) in a single transaction
        owned by the caller. The service never calls `commit`, `rollback`,
        `flush`, `refresh`, `expire`, or `begin`.

        Order of operations (validation-before-mutation):
        1. Load and validate the draft Pedido.
        2. Load and validate the source PedidoProducto line.
        3. Compute `cantidad_a_modificar` (explicit quantity or re-read
           source quantity); validate the quantity ceiling.
        4. Compute `cantidad_destino_a_modificar` (explicit destination
           quantity or the effective source quantity for backward
           compatibility); validate it is positive.
        5. Load and validate the destination ProductoPresentacion
           (existence, same comercio, active, available, presentation
           active).
        6. Run the equivalent-modification guard.
        7. Run the destination consolidation lookup.
        8. Read `current_precio` for any new destination line before any
           source mutation.
        9. Mutate the source and the destination atomically.

        Returns a `ModificationResult` whose `status` is either `"executed"`
        (with display names, quantities, and consolidation flags populated)
        or `"rejected"` (with a deterministic `reason`).
        """
        pedido = self._repo.pedido(pedido_id)
        if pedido is None:
            return ModificationResult(status="rejected", reason="pedido_not_found")
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            return ModificationResult(
                status="rejected", reason="pedido_not_editable"
            )

        source = self._repo.get_for_pedido(pedido_id, pedido_producto_origen_id)
        if source is None:
            return ModificationResult(
                status="rejected", reason="source_not_in_pedido"
            )

        source_pp = source.producto_presentacion
        source_producto = source_pp.producto
        source_presentacion = source_pp.presentacion
        source_pp_id = source_pp.id
        source_cantidad = source.cantidad

        cantidad_a_modificar = self._resolve_cantidad_a_modificar(
            cantidad, source_cantidad
        )
        if cantidad_a_modificar is None:
            return ModificationResult(status="rejected", reason="invalid_quantity")
        if cantidad is not None and cantidad > source_cantidad:
            return ModificationResult(
                status="rejected",
                reason="quantity_exceeds_source",
                cantidad_actual=source_cantidad,
                producto_origen_nombre=source_producto.nombre,
                presentacion_origen=source_presentacion.codigo,
            )

        cantidad_destino_a_modificar = self._resolve_cantidad_destino(
            cantidad_destino, cantidad_a_modificar
        )
        if cantidad_destino_a_modificar is None:
            return ModificationResult(status="rejected", reason="invalid_quantity")

        dest_pp = self._session.get(
            ProductoPresentacion, producto_presentacion_destino_id
        )
        if dest_pp is None:
            return ModificationResult(
                status="rejected", reason="destination_unavailable"
            )
        if not dest_pp.activo:
            return ModificationResult(
                status="rejected", reason="destination_unavailable"
            )
        if (
            not dest_pp.producto.activo
            or not dest_pp.producto.disponible
            or not dest_pp.presentacion.activo
        ):
            return ModificationResult(
                status="rejected", reason="destination_unavailable"
            )

        source_comercio_id = source_pp.presentacion.id_comercio
        dest_comercio_id = dest_pp.presentacion.id_comercio
        if source_comercio_id != dest_comercio_id:
            return ModificationResult(
                status="rejected", reason="destination_foreign_comercio"
            )

        if source_pp_id == producto_presentacion_destino_id:
            return ModificationResult(
                status="rejected", reason="equivalent_modification"
            )

        existing_dest = self._repo.get_by_pedido_and_producto_presentacion(
            pedido_id, producto_presentacion_destino_id
        )
        if existing_dest is None:
            precio = self._repo.current_precio(producto_presentacion_destino_id)
            if precio is None:
                return ModificationResult(
                    status="rejected", reason="destination_price_missing"
                )
        else:
            precio = None

        if cantidad_a_modificar >= source_cantidad:
            self._repo.delete(source)
            origen_eliminado = True
            cantidad_origen_restante = 0
        else:
            updated_source = self._repo.decrement(source.id, cantidad_a_modificar)
            origen_eliminado = False
            cantidad_origen_restante = updated_source.cantidad

        if existing_dest is not None:
            updated_dest = self._repo.increment(
                existing_dest.id, cantidad_destino_a_modificar
            )
            destino_creado = False
            cantidad_destino_final = updated_dest.cantidad
        else:
            assert precio is not None
            self._repo.create_with_price_snapshot(
                id_pedido=pedido_id,
                id_producto_presentacion=producto_presentacion_destino_id,
                cantidad=cantidad_destino_a_modificar,
                precio_unitario=precio.precio,
            )
            destino_creado = True
            cantidad_destino_final = cantidad_destino_a_modificar

        return ModificationResult(
            status="executed",
            producto_origen_nombre=source_producto.nombre,
            presentacion_origen=source_presentacion.codigo,
            producto_destino_nombre=dest_pp.producto.nombre,
            presentacion_destino=dest_pp.presentacion.codigo,
            cantidad_modificada=cantidad_a_modificar,
            cantidad_origen_restante=cantidad_origen_restante,
            cantidad_destino_final=cantidad_destino_final,
            origen_eliminado=origen_eliminado,
            destino_creado=destino_creado,
            cantidad_destino_modificada=cantidad_destino_a_modificar,
        )