from sqlalchemy import select
from sqlalchemy.orm import Session as SqlSession

from backend.models import EstadoSession, Session


class SessionRepository:
    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def get(self, session_id: int) -> Session | None:
        return self._session.get(Session, session_id)

    def exists(self, session_id: int) -> bool:
        return self._session.get(Session, session_id) is not None

    def get_active_by_comercio_cliente(
        self, id_comercio: int, id_cliente: int
    ) -> Session | None:
        stmt = (
            select(Session)
            .where(Session.id_comercio == id_comercio)
            .where(Session.id_cliente == id_cliente)
            .where(Session.estado_session == EstadoSession.ACTIVA)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        id_comercio: int,
        id_cliente: int,
        id_pedido: int | None,
    ) -> Session:
        row = Session(
            id_comercio=id_comercio,
            id_cliente=id_cliente,
            id_pedido=id_pedido,
            estado_session=EstadoSession.ACTIVA,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_pedido(self, session_row: Session, id_pedido: int | None) -> None:
        session_row.id_pedido = id_pedido
        self._session.flush()

    def set_estado(self, session_row: Session, estado: EstadoSession) -> None:
        session_row.estado_session = estado
        self._session.flush()

    def set_ultimo_movimiento(self, session_row: Session) -> None:
        from datetime import datetime
        from sqlalchemy import func

        session_row.datetime_ultimo_movimiento = func.now()
        self._session.flush()