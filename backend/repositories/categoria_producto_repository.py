from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import CategoriaProducto, Comercio


class CategoriaProductoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def comercio_exists(self, comercio_id: int) -> bool:
        return self._session.get(Comercio, comercio_id) is not None

    def list_by_comercio(self, comercio_id: int) -> list[CategoriaProducto]:
        stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(CategoriaProducto.orden, CategoriaProducto.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, categoria_producto_id: int) -> CategoriaProducto | None:
        return self._session.get(CategoriaProducto, categoria_producto_id)

    def create(
        self,
        comercio_id: int,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> CategoriaProducto:
        values: dict[str, object] = {
            "id_comercio": comercio_id,
            "descripcion": descripcion,
        }
        if activo is not None:
            values["activo"] = activo
        if orden is not None:
            values["orden"] = orden
        row = CategoriaProducto(**values)
        self._session.add(row)
        self._session.flush()
        return row
