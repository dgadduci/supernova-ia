from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ComercioMedioPago, MediosPago


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

    def list_active_for_comercio(self, comercio_id: int) -> list[MediosPago]:
        """Return the medios_pago rows that are globally active and enabled
        for the supplied comercio. The join enforces commerce isolation.
        """
        stmt = (
            select(MediosPago)
            .join(
                ComercioMedioPago,
                ComercioMedioPago.id_medio_pago == MediosPago.id,
            )
            .where(ComercioMedioPago.id_comercio == comercio_id)
            .where(ComercioMedioPago.activo.is_(True))
            .where(MediosPago.activo.is_(True))
            .order_by(MediosPago.id)
        )
        return list(self._session.execute(stmt).scalars())

    def create(self, codigo: str, descripcion: str, activo: bool) -> MediosPago:
        row = MediosPago(codigo=codigo, descripcion=descripcion, activo=activo)
        self._session.add(row)
        self._session.flush()
        return row
