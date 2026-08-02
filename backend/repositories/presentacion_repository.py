from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Comercio, Presentacion


class PresentacionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def comercio_exists(self, comercio_id: int) -> bool:
        return self._session.get(Comercio, comercio_id) is not None

    def list_by_comercio(self, comercio_id: int) -> list[Presentacion]:
        stmt = (
            select(Presentacion)
            .where(Presentacion.id_comercio == comercio_id)
            .order_by(Presentacion.orden, Presentacion.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, presentacion_id: int) -> Presentacion | None:
        return self._session.get(Presentacion, presentacion_id)

    def get_by_codigo(self, comercio_id: int, codigo: str) -> Presentacion | None:
        stmt = select(Presentacion).where(
            Presentacion.id_comercio == comercio_id,
            func.lower(Presentacion.codigo) == codigo.lower(),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_descripcion(self, comercio_id: int, descripcion: str) -> Presentacion | None:
        stmt = select(Presentacion).where(
            Presentacion.id_comercio == comercio_id,
            func.lower(Presentacion.descripcion) == descripcion.lower(),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        comercio_id: int,
        codigo: str,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> Presentacion:
        values: dict[str, object] = {
            "id_comercio": comercio_id,
            "codigo": codigo,
            "descripcion": descripcion,
        }
        if activo is not None:
            values["activo"] = activo
        if orden is not None:
            values["orden"] = orden
        row = Presentacion(**values)
        self._session.add(row)
        self._session.flush()
        return row
