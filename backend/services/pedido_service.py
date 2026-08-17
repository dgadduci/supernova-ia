from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import EstadoPedido, EstadoSession, Pedido, PedidoProducto
from backend.models import Session as _SESSION_MODEL
from backend.repositories.pedido_producto_repository import PedidoProductoRepository
from backend.repositories.pedido_repository import PedidoRepository
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.exceptions import (
    CommerceUnavailable,
    InvalidEstadoTransition,
    MediosPagoNotFound,
    MetodoEntregaNotFound,
    PedidoNotEditable,
    PedidoNotFound,
    SessionNotActive,
    SessionNotFound,
)

ALLOWED_TRANSITIONS: dict[EstadoPedido, set[EstadoPedido]] = {
    EstadoPedido.BORRADOR: {EstadoPedido.INGRESADO, EstadoPedido.CANCELADO},
    EstadoPedido.INGRESADO: {EstadoPedido.PREPARACION, EstadoPedido.CANCELADO},
    EstadoPedido.PREPARACION: {EstadoPedido.TERMINADO, EstadoPedido.CANCELADO},
    EstadoPedido.TERMINADO: {EstadoPedido.ENTREGADO},
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}


class PedidoService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = PedidoRepository(session)
        self._pedido_producto_repo = PedidoProductoRepository(session)

    def get_by_id(self, pedido_id: int) -> Pedido:
        pedido = self._repo.get(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        return pedido

    def get_detalle(self, pedido_id: int) -> tuple[Pedido, list[PedidoProducto]]:
        pedido = self._repo.get(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        lineas = self._pedido_producto_repo.list_by_pedido(pedido_id)
        return pedido, lineas

    def create(
        self,
        id_session: int,
        id_medio_pago: int | None,
        id_metodo_entrega: int | None,
        datetime_entrega_programada: datetime | None,
    ) -> Pedido:
        session_row = self._session.get(_SESSION_MODEL, id_session)
        if session_row is None:
            raise SessionNotFound(id_session)
        if session_row.estado_session != EstadoSession.ACTIVA:
            raise SessionNotActive(id_session)
        if id_medio_pago is not None and not self._repo.medio_pago_exists(id_medio_pago):
            raise MediosPagoNotFound(id_medio_pago)
        if id_metodo_entrega is not None and not self._repo.metodo_entrega_exists(id_metodo_entrega):
            raise MetodoEntregaNotFound(id_metodo_entrega)
        pedido = Pedido(
            id_session=id_session,
            id_medio_pago=id_medio_pago,
            id_metodo_entrega=id_metodo_entrega,
            datetime_entrega_programada=datetime_entrega_programada,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        try:
            self._repo.add(pedido)
            self._repo.flush()
            self._session.commit()
            self._session.refresh(pedido)
            return pedido
        except Exception:
            self._session.rollback()
            raise

    def set_medio_pago(self, pedido_id: int, id_medio_pago: int | None) -> Pedido:
        pedido = self._require_borrador(pedido_id)
        if id_medio_pago is not None and not self._repo.medio_pago_exists(id_medio_pago):
            raise MediosPagoNotFound(id_medio_pago)
        pedido.id_medio_pago = id_medio_pago
        try:
            self._repo.flush()
            self._session.commit()
            self._session.refresh(pedido)
            return pedido
        except Exception:
            self._session.rollback()
            raise

    def set_metodo_entrega(self, pedido_id: int, id_metodo_entrega: int | None) -> Pedido:
        pedido = self._require_borrador(pedido_id)
        if id_metodo_entrega is not None and not self._repo.metodo_entrega_exists(id_metodo_entrega):
            raise MetodoEntregaNotFound(id_metodo_entrega)
        pedido.id_metodo_entrega = id_metodo_entrega
        try:
            self._repo.flush()
            self._session.commit()
            self._session.refresh(pedido)
            return pedido
        except Exception:
            self._session.rollback()
            raise

    def set_fecha_entrega(self, pedido_id: int, fecha: datetime | None) -> Pedido:
        pedido = self._require_borrador(pedido_id)
        pedido.datetime_entrega_programada = fecha
        try:
            self._repo.flush()
            self._session.commit()
            self._session.refresh(pedido)
            return pedido
        except Exception:
            self._session.rollback()
            raise

    def cambiar_estado(self, pedido_id: int, nuevo_estado: EstadoPedido) -> Pedido:
        pedido = self._require_exists(pedido_id)
        self._assert_transition(pedido.estado_pedido, nuevo_estado)
        if (
            pedido.estado_pedido == EstadoPedido.BORRADOR
            and nuevo_estado == EstadoPedido.INGRESADO
        ):
            self._reserve_confirmed_order_or_raise(pedido)
        pedido.estado_pedido = nuevo_estado
        try:
            self._repo.flush()
            self._session.commit()
            self._session.refresh(pedido)
            return pedido
        except Exception:
            self._session.rollback()
            raise

    def _reserve_confirmed_order_or_raise(self, pedido: Pedido) -> None:
        """Reserve a trial quota unit before flipping a pedido to INGRESADO.

        The helper is only invoked for the ``BORRADOR -> INGRESADO``
        transition. It locks the comercio row, re-evaluates the
        trial window / quota inside the lock, and increments the
        counter atomically with the caller-owned transition. The
        caller owns the surrounding transaction: a subsequent
        failure rolls back both the pedido stage and the counter
        stage together.
        """
        from backend.models import Session as ConversationSession

        session_row = self._session.get(ConversationSession, int(pedido.id_session))
        if session_row is None:
            raise CommerceUnavailable("session missing for pedido")
        comercio_id = getattr(session_row, "id_comercio", None)
        if comercio_id is None:
            raise CommerceUnavailable("commerce missing for pedido")
        outcome = CommerceAvailabilityService(
            self._session
        ).reserve_confirmed_order(int(comercio_id))
        if outcome.status is not CommerceAvailabilityStatus.AVAILABLE:
            reason = (
                outcome.reason.value if outcome.reason is not None else "blocked_state"
            )
            raise CommerceUnavailable(
                f"comercio {comercio_id} no disponible: {reason}"
            )

    def _require_exists(self, pedido_id: int) -> Pedido:
        pedido = self._repo.get(pedido_id)
        if pedido is None:
            raise PedidoNotFound(pedido_id)
        return pedido

    def _require_borrador(self, pedido_id: int) -> Pedido:
        pedido = self._require_exists(pedido_id)
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise PedidoNotEditable(pedido_id, pedido.estado_pedido.value)
        return pedido

    @staticmethod
    def _assert_transition(actual: EstadoPedido, nuevo: EstadoPedido) -> None:
        if nuevo not in ALLOWED_TRANSITIONS[actual]:
            raise InvalidEstadoTransition(actual.value, nuevo.value)