from sqlalchemy.orm import Session

from backend.models import Producto
from backend.repositories.producto_repository import ProductoRepository
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    DuplicateProductoNombre,
    InvalidProducto,
    ProductoNotFound,
)


class ProductoService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ProductoRepository(session)

    def list_by_categoria(self, categoria_producto_id: int) -> list[Producto]:
        self._require_categoria(categoria_producto_id)
        return self._repo.list_by_categoria(categoria_producto_id)

    def list_by_comercio(self, comercio_id: int) -> list[Producto]:
        if not self._repo.comercio_exists(comercio_id):
            raise ComercioNotFound(comercio_id)
        return self._repo.list_by_comercio(comercio_id)

    def get_by_id(self, producto_id: int) -> Producto:
        row = self._repo.get_by_id(producto_id)
        if row is None:
            raise ProductoNotFound(producto_id)
        return row

    def create(
        self,
        categoria_producto_id: int,
        nombre: str,
        descripcion: str | None,
        activo: bool | None,
        disponible: bool | None,
        orden: int | None,
    ) -> Producto:
        self._require_categoria(categoria_producto_id)
        cleaned_nombre = nombre.strip()
        if not cleaned_nombre:
            raise InvalidProducto("nombre must not be empty")
        cleaned_descripcion = descripcion.strip() if descripcion is not None else None
        if cleaned_descripcion == "":
            cleaned_descripcion = None
        if self._repo.get_by_nombre(categoria_producto_id, cleaned_nombre) is not None:
            raise DuplicateProductoNombre(cleaned_nombre)
        try:
            row = self._repo.create(
                categoria_producto_id,
                cleaned_nombre,
                cleaned_descripcion,
                activo,
                disponible,
                orden,
            )
            self._session.commit()
            return row
        except Exception:
            self._session.rollback()
            raise

    def _require_categoria(self, categoria_producto_id: int) -> None:
        if not self._repo.categoria_exists(categoria_producto_id):
            raise CategoriaProductoNotFound(categoria_producto_id)
