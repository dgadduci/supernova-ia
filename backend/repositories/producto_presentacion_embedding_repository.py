from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ProductoPresentacion, ProductoPresentacionEmbedding


class ProductoPresentacionEmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def producto_presentacion_exists(self, id_producto_presentacion: int) -> bool:
        return self._session.get(ProductoPresentacion, id_producto_presentacion) is not None

    def get_by_id(self, embedding_id: int) -> ProductoPresentacionEmbedding | None:
        return self._session.get(ProductoPresentacionEmbedding, embedding_id)

    def get_by_identity(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> ProductoPresentacionEmbedding | None:
        stmt = select(ProductoPresentacionEmbedding).where(
            ProductoPresentacionEmbedding.id_producto_presentacion
            == id_producto_presentacion,
            ProductoPresentacionEmbedding.modelo == modelo,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> ProductoPresentacionEmbedding | None:
        return self.get_by_identity(id_producto_presentacion, modelo)

    def list_by_producto_presentacion(
        self,
        id_producto_presentacion: int,
    ) -> list[ProductoPresentacionEmbedding]:
        stmt = (
            select(ProductoPresentacionEmbedding)
            .where(
                ProductoPresentacionEmbedding.id_producto_presentacion
                == id_producto_presentacion
            )
            .order_by(ProductoPresentacionEmbedding.modelo)
        )
        return list(self._session.execute(stmt).scalars())

    def create(
        self,
        id_producto_presentacion: int,
        vector: Sequence[float],
        modelo: str,
    ) -> ProductoPresentacionEmbedding:
        row = ProductoPresentacionEmbedding(
            id_producto_presentacion=id_producto_presentacion,
            vector=list(vector),
            modelo=modelo,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update(
        self,
        row: ProductoPresentacionEmbedding,
        vector: Sequence[float],
        modelo: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        row.vector = list(vector)
        if modelo is not None:
            row.modelo = modelo
        row.fecha_ultima_modificacion = datetime.now(timezone.utc)
        self._session.flush()
        return row

    def create_or_update(
        self,
        id_producto_presentacion: int,
        vector: Sequence[float],
        modelo: str,
    ) -> ProductoPresentacionEmbedding:
        existing = self.get_by_identity(id_producto_presentacion, modelo)
        if existing is None:
            return self.create(id_producto_presentacion, vector, modelo)
        return self.update(existing, vector)

    def upsert(
        self,
        id_producto_presentacion: int,
        vector: Sequence[float],
        modelo: str,
    ) -> ProductoPresentacionEmbedding:
        return self.create_or_update(id_producto_presentacion, vector, modelo)

    def get_by_producto_presentacion(
        self,
        id_producto_presentacion: int,
    ) -> list[ProductoPresentacionEmbedding]:
        return self.list_by_producto_presentacion(id_producto_presentacion)


__all__ = ["ProductoPresentacionEmbeddingRepository"]
