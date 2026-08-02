from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Comercio, EstadoComercio


class EstadoComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[EstadoComercio]:
        stmt = select(EstadoComercio).order_by(EstadoComercio.id)
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, estado_id: int) -> EstadoComercio | None:
        return self._session.get(EstadoComercio, estado_id)

    def get_by_estado(self, estado: str) -> EstadoComercio | None:
        stmt = select(EstadoComercio).where(EstadoComercio.estado == estado)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, estado: str) -> EstadoComercio:
        row = EstadoComercio(estado=estado)
        self._session.add(row)
        self._session.flush()
        return row

    def estado_in_use(self, estado_id: int) -> bool:
        stmt = select(Comercio.id).where(Comercio.estado_id == estado_id).limit(1)
        return self._session.execute(stmt).first() is not None
