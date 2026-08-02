from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import CategoriaProducto, Comercio, Producto


class ProductoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def categoria_exists(self, categoria_producto_id: int) -> bool:
        return self._session.get(CategoriaProducto, categoria_producto_id) is not None

    def comercio_exists(self, comercio_id: int) -> bool:
        return self._session.get(Comercio, comercio_id) is not None

    def list_by_categoria(self, categoria_producto_id: int) -> list[Producto]:
        stmt = (
            select(Producto)
            .where(Producto.id_categoria_producto == categoria_producto_id)
            .order_by(Producto.orden, Producto.id)
        )
        return list(self._session.execute(stmt).scalars())

    def list_by_comercio(self, comercio_id: int) -> list[Producto]:
        stmt = (
            select(Producto)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(CategoriaProducto.orden, Producto.orden, Producto.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, producto_id: int) -> Producto | None:
        return self._session.get(Producto, producto_id)

    def get_by_nombre(
        self,
        categoria_producto_id: int,
        nombre: str,
    ) -> Producto | None:
        stmt = select(Producto).where(
            Producto.id_categoria_producto == categoria_producto_id,
            func.lower(Producto.nombre) == nombre.lower(),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        categoria_producto_id: int,
        nombre: str,
        descripcion: str | None,
        activo: bool | None,
        disponible: bool | None,
        orden: int | None,
    ) -> Producto:
        values: dict[str, object] = {
            "id_categoria_producto": categoria_producto_id,
            "nombre": nombre,
            "descripcion": descripcion,
        }
        if activo is not None:
            values["activo"] = activo
        if disponible is not None:
            values["disponible"] = disponible
        if orden is not None:
            values["orden"] = orden
        row = Producto(**values)
        self._session.add(row)
        self._session.flush()
        return row
