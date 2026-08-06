"""Per-document SQLAlchemy reads and writes for ``producto_presentacion_embeddings``.

Subphase 4.6 rewrites the persistence boundary from one aggregate row
per ``(id_producto_presentacion, modelo)`` to one row per semantic
document. The repository is intentionally narrow: it performs only
SQLAlchemy reads and writes (``find_by_document``, ``list_*``,
``insert_document``, ``update_document``, ``mark_status``). It does NOT
compute hash equality, does NOT decide between created / updated /
unchanged / failed, and does NOT own commit / rollback / close / begin.

``update_document(row, *, source_text, normalized_text, content_hash,
vector, embedding_status, activo, last_error)`` persists the complete
document metadata and advances ``fecha_ultima_modificacion``. The
reconciliation decisions remain in the service / indexer.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.models import (
    ProductoPresentacion,
    ProductoPresentacionEmbedding,
)


class ProductoPresentacionEmbeddingRepository:
    """Per-document reads and writes for per-document embeddings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- Read helpers --------------------------------------------------------

    def producto_presentacion_exists(
        self, id_producto_presentacion: int
    ) -> bool:
        return (
            self._session.get(ProductoPresentacion, id_producto_presentacion)
            is not None
        )

    def get_by_id(
        self, embedding_id: int
    ) -> ProductoPresentacionEmbedding | None:
        return self._session.get(ProductoPresentacionEmbedding, embedding_id)

    def find_by_document(
        self,
        id_producto_presentacion: int,
        modelo: str,
        source_type: str,
        source_record_id: int | None,
    ) -> ProductoPresentacionEmbedding | None:
        if source_record_id is None:
            stmt = select(ProductoPresentacionEmbedding).where(
                ProductoPresentacionEmbedding.id_producto_presentacion
                == id_producto_presentacion,
                ProductoPresentacionEmbedding.modelo == modelo,
                ProductoPresentacionEmbedding.source_type == source_type,
                ProductoPresentacionEmbedding.source_record_id.is_(None),
            )
        else:
            stmt = select(ProductoPresentacionEmbedding).where(
                ProductoPresentacionEmbedding.id_producto_presentacion
                == id_producto_presentacion,
                ProductoPresentacionEmbedding.modelo == modelo,
                ProductoPresentacionEmbedding.source_type == source_type,
                ProductoPresentacionEmbedding.source_record_id
                == source_record_id,
            )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        stmt = select(ProductoPresentacionEmbedding).where(
            ProductoPresentacionEmbedding.id_producto_presentacion
            == id_producto_presentacion,
            ProductoPresentacionEmbedding.modelo == modelo,
        )
        return list(self._session.execute(stmt).scalars())

    def list_by_producto_presentacion(
        self,
        id_producto_presentacion: int,
    ) -> list[ProductoPresentacionEmbedding]:
        stmt = select(ProductoPresentacionEmbedding).where(
            ProductoPresentacionEmbedding.id_producto_presentacion
            == id_producto_presentacion
        )
        return list(self._session.execute(stmt).scalars())

    def list_by_producto(
        self,
        id_producto: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        stmt = (
            select(ProductoPresentacionEmbedding)
            .join(
                ProductoPresentacion,
                ProductoPresentacionEmbedding.id_producto_presentacion
                == ProductoPresentacion.id,
            )
            .where(
                ProductoPresentacion.id_producto == id_producto,
                ProductoPresentacionEmbedding.modelo == modelo,
            )
        )
        return list(self._session.execute(stmt).scalars())

    def list_by_comercio(
        self,
        id_comercio: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        from backend.models import (
            CategoriaProducto,
            Producto,
        )

        stmt = (
            select(ProductoPresentacionEmbedding)
            .join(
                ProductoPresentacion,
                ProductoPresentacionEmbedding.id_producto_presentacion
                == ProductoPresentacion.id,
            )
            .join(Producto, ProductoPresentacion.id_producto == Producto.id)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .where(
                CategoriaProducto.id_comercio == id_comercio,
                ProductoPresentacionEmbedding.modelo == modelo,
            )
            .options(
                joinedload(ProductoPresentacionEmbedding.producto_presentacion)
            )
        )
        return list(self._session.execute(stmt).scalars())

    # -- Write helpers -------------------------------------------------------

    def insert_document(
        self,
        *,
        id_producto_presentacion: int,
        modelo: str,
        source_type: str,
        source_record_id: int | None,
        source_text: str,
        normalized_text: str,
        content_hash: str,
        vector: Sequence[float] | None,
        embedding_status: str,
        activo: bool = True,
        last_error: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        row = ProductoPresentacionEmbedding(
            id_producto_presentacion=id_producto_presentacion,
            modelo=modelo,
            source_type=source_type,
            source_record_id=source_record_id,
            source_text=source_text,
            normalized_text=normalized_text,
            content_hash=content_hash,
            vector=list(vector) if vector is not None else None,
            embedding_status=embedding_status,
            activo=activo,
            last_error=last_error,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_document(
        self,
        row: ProductoPresentacionEmbedding,
        *,
        source_text: str,
        normalized_text: str,
        content_hash: str,
        vector: Sequence[float] | None,
        embedding_status: str,
        activo: bool,
        last_error: str | None,
    ) -> ProductoPresentacionEmbedding:
        row.source_text = source_text
        row.normalized_text = normalized_text
        row.content_hash = content_hash
        if vector is not None:
            row.vector = list(vector)
        row.embedding_status = embedding_status
        row.activo = activo
        row.last_error = last_error
        row.fecha_ultima_modificacion = datetime.now(timezone.utc)
        self._session.flush()
        return row

    def mark_status(
        self,
        row: ProductoPresentacionEmbedding,
        new_status: str,
    ) -> ProductoPresentacionEmbedding:
        row.embedding_status = new_status
        row.fecha_ultima_modificacion = datetime.now(timezone.utc)
        self._session.flush()
        return row

    # -- Back-compat aggregate wrappers (deprecated) ------------------------

    def get_by_identity(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> ProductoPresentacionEmbedding | None:
        return self.find_by_document(
            id_producto_presentacion,
            modelo,
            source_type="canonical",
            source_record_id=None,
        )

    def get_by_producto_presentacion_and_model(
        self,
        id_producto_presentacion: int,
        modelo: str,
    ) -> ProductoPresentacionEmbedding | None:
        return self.get_by_identity(id_producto_presentacion, modelo)

    def create(
        self,
        id_producto_presentacion: int,
        vector: Sequence[float],
        modelo: str,
    ) -> ProductoPresentacionEmbedding:
        return self.insert_document(
            id_producto_presentacion=id_producto_presentacion,
            modelo=modelo,
            source_type="canonical",
            source_record_id=None,
            source_text=_vector_to_placeholder_text(vector),
            normalized_text=_vector_to_placeholder_text(vector),
            content_hash="0" * 64,
            vector=vector,
            embedding_status="ready",
            activo=True,
            last_error=None,
        )

    def update(
        self,
        row: ProductoPresentacionEmbedding,
        vector: Sequence[float],
        modelo: str | None = None,
    ) -> ProductoPresentacionEmbedding:
        return self.update_document(
            row,
            source_text=row.source_text,
            normalized_text=row.normalized_text,
            content_hash=row.content_hash,
            vector=vector,
            embedding_status=row.embedding_status,
            activo=row.activo,
            last_error=row.last_error,
        )

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


def _vector_to_placeholder_text(vector: Sequence[float]) -> str:
    """Render a short placeholder text for legacy aggregate wrappers.

    The legacy aggregate surface does not carry source_text /
    normalized_text / content_hash because it predates the per-document
    shape. The deprecated wrappers preserve the existing public surface
    by writing a short placeholder so the per-document ``CHECK``
    constraints (``nonempty_chk`` / ``content_hash_chk``) are satisfied.
    """
    return f"legacy aggregate embedding (dim={len(vector)})"


__all__ = ["ProductoPresentacionEmbeddingRepository"]
