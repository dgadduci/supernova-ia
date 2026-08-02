from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Precio
from backend.repositories.precio_repository import PrecioRepository
from backend.services.exceptions import (
    DuplicatePrecio,
    InvalidPrecio,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)


class PrecioService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = PrecioRepository(session)

    def get_by_id(self, precio_id: int) -> Precio:
        row = self._repo.get_by_id(precio_id)
        if row is None:
            raise PrecioNotFound(precio_id)
        return row

    def get_by_producto_presentacion(
        self,
        producto_presentacion_id: int,
    ) -> Precio:
        self._require_producto_presentacion(producto_presentacion_id)
        row = self._repo.get_by_producto_presentacion(producto_presentacion_id)
        if row is None:
            raise PrecioNotFound(producto_presentacion_id)
        return row

    def create(
        self,
        producto_presentacion_id: int,
        precio: Decimal,
    ) -> Precio:
        self._require_producto_presentacion(producto_presentacion_id)
        if precio < 0:
            raise InvalidPrecio("precio must not be negative")
        normalized_precio = precio.quantize(Decimal("0.01"))
        if self._repo.get_by_producto_presentacion(producto_presentacion_id) is not None:
            raise DuplicatePrecio(producto_presentacion_id)
        try:
            row = self._repo.create(producto_presentacion_id, normalized_precio)
            self._session.commit()
            return row
        except Exception:
            self._session.rollback()
            raise

    def _require_producto_presentacion(self, producto_presentacion_id: int) -> None:
        if not self._repo.producto_presentacion_exists(producto_presentacion_id):
            raise ProductoPresentacionNotFound(producto_presentacion_id)
