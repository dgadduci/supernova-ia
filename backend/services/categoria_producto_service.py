from sqlalchemy.orm import Session

from backend.models import CategoriaProducto
from backend.repositories.categoria_producto_repository import CategoriaProductoRepository
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidCategoriaProducto,
)


class CategoriaProductoService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CategoriaProductoRepository(session)

    def list_by_comercio(self, comercio_id: int) -> list[CategoriaProducto]:
        self._require_comercio(comercio_id)
        return self._repo.list_by_comercio(comercio_id)

    def get_by_id(self, categoria_producto_id: int) -> CategoriaProducto:
        row = self._repo.get_by_id(categoria_producto_id)
        if row is None:
            raise CategoriaProductoNotFound(categoria_producto_id)
        return row

    def create(
        self,
        comercio_id: int,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> CategoriaProducto:
        self._require_comercio(comercio_id)
        cleaned_descripcion = descripcion.strip()
        if not cleaned_descripcion:
            raise InvalidCategoriaProducto("descripcion must not be empty")
        try:
            row = self._repo.create(
                comercio_id,
                cleaned_descripcion,
                activo,
                orden,
            )
            self._session.commit()
            return row
        except Exception:
            self._session.rollback()
            raise

    def _require_comercio(self, comercio_id: int) -> None:
        if not self._repo.comercio_exists(comercio_id):
            raise ComercioNotFound(comercio_id)
