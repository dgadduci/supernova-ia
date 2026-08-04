from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Presentacion,
    Producto,
    ProductoAlias,
    ProductoPresentacion,
)


class ProductoAliasRepository:
    """SQLAlchemy queries for ``producto_aliases``.

    All alias-related database access lives here. Services MUST NOT issue
    queries directly; they call into this repository so that the fuzzy
    recognizer remains infrastructure-free.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        id_producto: int,
        id_producto_presentacion: int | None,
        alias: str,
        alias_normalizado: str,
        activo: bool | None,
    ) -> ProductoAlias:
        values: dict[str, object] = {
            "id_producto": id_producto,
            "id_producto_presentacion": id_producto_presentacion,
            "alias": alias,
            "alias_normalizado": alias_normalizado,
        }
        if activo is not None:
            values["activo"] = activo
        row = ProductoAlias(**values)
        self._session.add(row)
        self._session.flush()
        return row

    def find_same_scope(
        self,
        id_producto: int,
        id_producto_presentacion: int | None,
        alias_normalizado: str,
        include_inactive: bool = False,
    ) -> ProductoAlias | None:
        stmt = select(ProductoAlias).where(
            ProductoAlias.id_producto == id_producto,
            ProductoAlias.alias_normalizado == alias_normalizado,
        )
        if id_producto_presentacion is None:
            stmt = stmt.where(ProductoAlias.id_producto_presentacion.is_(None))
        else:
            stmt = stmt.where(
                ProductoAlias.id_producto_presentacion == id_producto_presentacion
            )
        if not include_inactive:
            stmt = stmt.where(ProductoAlias.activo.is_(True))
        return self._session.execute(stmt).scalar_one_or_none()

    def list_active_by_producto_ids(
        self,
        id_producto_values: list[int],
    ) -> list[ProductoAlias]:
        if not id_producto_values:
            return []
        stmt = select(ProductoAlias).where(
            ProductoAlias.id_producto.in_(id_producto_values),
            ProductoAlias.id_producto_presentacion.is_(None),
            ProductoAlias.activo.is_(True),
        )
        return list(self._session.execute(stmt).scalars())

    def list_active_by_producto_presentacion_ids(
        self,
        id_producto_presentacion_values: list[int],
    ) -> list[ProductoAlias]:
        if not id_producto_presentacion_values:
            return []
        stmt = select(ProductoAlias).where(
            ProductoAlias.id_producto_presentacion.in_(
                id_producto_presentacion_values
            ),
            ProductoAlias.activo.is_(True),
        )
        return list(self._session.execute(stmt).scalars())

    def list_recognition_data(
        self,
        id_producto_values: list[int],
        id_producto_presentacion_values: list[int],
    ) -> list[ProductoAlias]:
        """Batched load of all active aliases applicable to the supplied IDs.

        Combines the product-wide and presentation-specific queries in a
        single batched read so catalog projection never queries per row.
        """
        product_aliases = self.list_active_by_producto_ids(id_producto_values)
        presentation_aliases = self.list_active_by_producto_presentacion_ids(
            id_producto_presentacion_values
        )
        return [*product_aliases, *presentation_aliases]

    def find_canonical_producto_in_comercio(
        self,
        comercio_id: int,
        nombre: str,
    ) -> Producto | None:
        stmt = (
            select(Producto)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .where(
                CategoriaProducto.id_comercio == comercio_id,
                Producto.nombre == nombre,
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_presentaciones_for_producto(
        self,
        id_producto: int,
    ) -> list[ProductoPresentacion]:
        stmt = select(ProductoPresentacion).where(
            ProductoPresentacion.id_producto == id_producto
        )
        return list(self._session.execute(stmt).scalars())

    def find_presentacion_by_codigo(
        self,
        id_producto: int,
        presentacion_codigo: str,
    ) -> list[ProductoPresentacion]:
        stmt = (
            select(ProductoPresentacion)
            .join(Presentacion, ProductoPresentacion.id_presentacion == Presentacion.id)
            .where(
                ProductoPresentacion.id_producto == id_producto,
                Presentacion.codigo == presentacion_codigo,
            )
        )
        return list(self._session.execute(stmt).scalars())

    def list_productos_in_comercio(self, comercio_id: int) -> list[Producto]:
        stmt = (
            select(Producto)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .where(CategoriaProducto.id_comercio == comercio_id)
        )
        return list(self._session.execute(stmt).scalars())


__all__ = ["ProductoAliasRepository"]
