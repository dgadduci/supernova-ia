from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SqlSession

from backend.models import EstadoPedido, EstadoSession, Pedido, Session
from backend.repositories.session_repository import SessionRepository
from backend.services.exceptions import (
    DuplicateActiveSession,
    IncompatiblePedidoAssociation,
    SessionAlreadyClosed,
    SessionNotActive,
    SessionNotFound,
)


class SessionService:
    def __init__(self, session: SqlSession) -> None:
        self._session = session
        self._repo = SessionRepository(session)

    def get_by_id(self, session_id: int) -> Session:
        row = self._repo.get(session_id)
        if row is None:
            raise SessionNotFound(session_id)
        return row

    def get_active(self, id_comercio: int, id_cliente: int) -> Session:
        row = self._repo.get_active_by_comercio_cliente(id_comercio, id_cliente)
        if row is None:
            raise SessionNotFound((id_comercio, id_cliente))
        return row

    def create(
        self,
        id_comercio: int,
        id_cliente: int,
        id_pedido: int | None,
    ) -> Session:
        try:
            row = self._repo.create(id_comercio, id_cliente, id_pedido)
            self._session.commit()
            self._session.refresh(row)
            return row
        except IntegrityError as e:
            self._session.rollback()
            if "uq_session_activa_comercio_cliente" in str(e.orig):
                raise DuplicateActiveSession((id_comercio, id_cliente)) from e
            raise

    def update_movimiento(self, session_id: int) -> Session:
        session_row = self._repo.get(session_id)
        if session_row is None:
            raise SessionNotFound(session_id)
        if session_row.estado_session != EstadoSession.ACTIVA:
            raise SessionNotActive(session_id)
        try:
            self._repo.set_ultimo_movimiento(session_row)
            self._session.commit()
            self._session.refresh(session_row)
            return session_row
        except Exception:
            self._session.rollback()
            raise

    def asociar_pedido(self, session_id: int, id_pedido: int) -> Session:
        session_row = self._repo.get(session_id)
        if session_row is None:
            raise SessionNotFound(session_id)
        if session_row.estado_session != EstadoSession.ACTIVA:
            raise SessionNotActive(session_id)

        pedido = self._session.get(Pedido, id_pedido)
        if pedido is None:
            from backend.services.exceptions import PedidoNotFound
            raise PedidoNotFound(id_pedido)

        if pedido.id_session != session_id:
            raise IncompatiblePedidoAssociation(
                f"pedido {id_pedido} belongs to session {pedido.id_session}, not {session_id}"
            )
        if pedido.estado_pedido != EstadoPedido.BORRADOR:
            raise IncompatiblePedidoAssociation(
                f"pedido must be in borrador to associate (current: {pedido.estado_pedido.value})"
            )

        try:
            self._repo.set_pedido(session_row, id_pedido)
            self._repo.set_ultimo_movimiento(session_row)
            self._session.commit()
            self._session.refresh(session_row)
            return session_row
        except Exception:
            self._session.rollback()
            raise

    def cerrar(self, session_id: int) -> Session:
        session_row = self._repo.get(session_id)
        if session_row is None:
            raise SessionNotFound(session_id)
        if session_row.estado_session == EstadoSession.CERRADA:
            raise SessionAlreadyClosed(session_id)
        try:
            self._repo.set_estado(session_row, EstadoSession.CERRADA)
            self._repo.set_ultimo_movimiento(session_row)
            self._session.commit()
            self._session.refresh(session_row)
            return session_row
        except Exception:
            self._session.rollback()
            raise