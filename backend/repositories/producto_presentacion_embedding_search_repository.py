"""Read-only pgvector cosine-distance search over
``producto_presentacion_embeddings``.

Subphase 4.9 introduces a single-purpose repository that performs the
vector search query backing the new
:class:`ProductPresentationVectorSearchService`. The repository is
intentionally narrow:

- It MUST NOT issue ``INSERT``, ``UPDATE``, or ``DELETE`` statements.
- It MUST NOT call ``session.commit``, ``session.rollback``,
  ``session.close``, or ``session.begin``.
- It MUST NOT import FastAPI, HTTP, the embedding client, the document
  builder, the seeder, the indexer, the sync service, or any router.

The query joins the parent chain
``ProductoPresentacionEmbedding × ProductoPresentacion × Producto ×
CategoriaProducto × Presentacion`` and filters on
``CategoriaProducto.id_comercio == id_comercio`` so other comercios
are never considered. The cosine distance is computed through the
pgvector ``<=>`` operator exposed by the existing
``VECTOR(EMBEDDING_DIMENSION)`` mapping. The ``ROW_NUMBER() OVER
(PARTITION BY id_producto_presentacion ORDER BY distance ASC)`` window
function collapses multiple documents for one presentation into a
single best-scoring row, and the outer ``LIMIT top_k`` counts unique
product-presentations rather than raw documents.

The repository trusts the service layer: ``top_k`` and
``query_embedding`` validation already happened upstream, so the SQL
path is invoked only with a positive ``top_k``, a correctly sized
embedding, and (optionally) a candidate id list.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from backend.models import (
    CategoriaProducto,
    EmbeddingStatus,
    Presentacion,
    Producto,
    ProductoPresentacion,
    ProductoPresentacionEmbedding,
)


class ProductoPresentacionEmbeddingSearchRepository:
    """Read-only pgvector cosine-distance search surface."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding: Sequence[float],
        modelo: str,
        top_k: int,
        candidate_ids: Sequence[int] | None = None,
    ) -> list[dict[str, object]]:
        """Return the best matching presentation per ``id_producto_presentacion``.

        The single SQL statement:

        1. Joins the full parent chain so commerce isolation, model
           isolation, embedding-status filtering, and the activity
           chain can be enforced.
        2. Filters on ``CategoriaProducto.id_comercio == id_comercio``.
        3. Filters on ``modelo == settings.embedding_model``.
        4. Filters on ``embedding_status == 'ready'``.
        5. Filters on the activity chain (``Producto.activo``,
           ``Producto.disponible``, ``ProductoPresentacion.activo``,
           ``CategoriaProducto.activo``, ``Presentacion.activo``).
        6. Optionally filters on ``id_producto_presentacion IN
           (candidate_ids)``.
        7. Computes the cosine distance through the pgvector ``<=>``
           operator exposed by the ``VECTOR(EMBEDDING_DIMENSION)``
           mapping.
        8. Wraps the result in a ``ROW_NUMBER() OVER (PARTITION BY
           id_producto_presentacion ORDER BY distance ASC)`` window
           function so only the best-scoring document per presentation
           survives.
        9. Applies ``LIMIT top_k`` AFTER the grouping so ``top_k``
           counts unique product-presentations.
        10. Orders by ``score DESC`` (most similar first), then by
            ``id_producto_presentacion ASC`` for deterministic ties.

        Returns a list of plain dicts carrying
        ``id_producto_presentacion``, ``source_type``, ``score`` (the
        cosine similarity ``1 - cosine_distance``), and the raw
        ``distance`` value (kept internal to the service mapping).
        """
        distance_expr = self._cosine_distance_expr(query_embedding)
        score_expr = (1.0 - distance_expr).cast(Float).label("score")
        row_number = (
            func.row_number()
            .over(
                partition_by=ProductoPresentacionEmbedding.id_producto_presentacion,
                order_by=distance_expr.asc(),
            )
            .label("row_number")
        )

        stmt = (
            select(
                ProductoPresentacionEmbedding.id_producto_presentacion.label(
                    "id_producto_presentacion"
                ),
                ProductoPresentacionEmbedding.source_type.label("source_type"),
                distance_expr.label("distance"),
                score_expr,
                row_number,
            )
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
            .join(
                Presentacion,
                ProductoPresentacion.id_presentacion == Presentacion.id,
            )
            .where(
                CategoriaProducto.id_comercio == id_comercio,
                ProductoPresentacionEmbedding.modelo == modelo,
                ProductoPresentacionEmbedding.embedding_status
                == EmbeddingStatus.READY.value,
                ProductoPresentacionEmbedding.activo.is_(True),
                Producto.activo.is_(True),
                ProductoPresentacion.activo.is_(True),
                CategoriaProducto.activo.is_(True),
                Presentacion.activo.is_(True),
                Producto.disponible.is_(True),
            )
        )
        if candidate_ids is not None:
            stmt = stmt.where(
                ProductoPresentacionEmbedding.id_producto_presentacion.in_(
                    list(candidate_ids)
                )
            )

        inner = stmt.subquery()
        outer = (
            select(
                inner.c.id_producto_presentacion,
                inner.c.source_type,
                inner.c.distance,
                inner.c.score,
            )
            .where(inner.c.row_number == 1)
            .order_by(inner.c.score.desc(), inner.c.id_producto_presentacion.asc())
            .limit(top_k)
        )
        rows = self._session.execute(outer).all()
        return [
            {
                "id_producto_presentacion": int(row.id_producto_presentacion),
                "source_type": str(row.source_type),
                "distance": float(row.distance),
                "score": float(row.score),
            }
            for row in rows
        ]

    def _cosine_distance_expr(
        self, query_embedding: Sequence[float]
    ) -> ColumnElement[float]:
        """Return the pgvector cosine distance expression.

        ``ProductoPresentacionEmbedding.vector`` is declared as
        ``VECTOR(EMBEDDING_DIMENSION)``; pgvector exposes the ``<=>``
        cosine-distance operator through the column's
        ``Comparator.cosine_distance`` method (provided by the
        ``VECTOR`` user-defined type). Binding the query vector as a
        Python list lets the ``VECTOR`` ``bind_processor`` convert it
        to the wire format pgvector expects.
        """
        distance: ColumnElement[float] = (
            ProductoPresentacionEmbedding.vector.cosine_distance(
                list(query_embedding)
            )
        ).cast(Float)
        return distance


__all__ = ["ProductoPresentacionEmbeddingSearchRepository"]