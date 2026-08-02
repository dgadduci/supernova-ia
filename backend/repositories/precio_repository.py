from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Precio, ProductoPresentacion


class PrecioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def producto_presentacion_exists(self, producto_presentacion_id: int) -> bool:
        return self._session.get(ProductoPresentacion, producto_presentacion_id) is not None

    def get_by_id(self, precio_id: int) -> Precio | None:
        return self._session.get(Precio, precio_id)

    def get_by_producto_presentacion(
        self,
        producto_presentacion_id: int,
    ) -> Precio | None:
        stmt = select(Precio).where(
            Precio.id_producto_presentacion == producto_presentacion_id
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        producto_presentacion_id: int,
        precio: Decimal,
    ) -> Precio:
        row = Precio(
            id_producto_presentacion=producto_presentacion_id,
            precio=precio,
        )
        self._session.add(row)
        self._session.flush()
        return row
