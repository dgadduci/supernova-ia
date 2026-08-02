from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import MediosPago


class MediosPagoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[MediosPago]:
        stmt = select(MediosPago).order_by(MediosPago.id)
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, medio_pago_id: int) -> MediosPago | None:
        return self._session.get(MediosPago, medio_pago_id)

    def get_by_codigo(self, codigo: str) -> MediosPago | None:
        stmt = select(MediosPago).where(MediosPago.codigo == codigo)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, codigo: str, descripcion: str, activo: bool) -> MediosPago:
        row = MediosPago(codigo=codigo, descripcion=descripcion, activo=activo)
        self._session.add(row)
        self._session.flush()
        return row
