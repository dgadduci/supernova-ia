"""Commerce-isolated aggregations for ``producto_presentacion_embeddings``.

Subphase 4.7 introduces a read-only repository that publishes the
``ProductoPresentacionEmbeddingStatusRepository`` for the new
local-admin ``GET /admin/comercios/{comercio_id}/product-embeddings/status``
endpoint. The repository exposes per-status, per-source-type, and
total / active / last-error aggregations over the existing 4.6
per-document table for a single ``comercio_id`` and ``modelo``.

The repository is intentionally read-only:

- It MUST NOT import HTTP, FastAPI, the embedding client, the
  indexer, the seeder, the admin service, or any router.
- It MUST NOT call ``commit``, ``rollback``, ``close``, or ``begin``.
- It MUST NOT issue ``INSERT``, ``UPDATE``, or ``DELETE`` statements.

The aggregations JOIN the parent chain
``ProductoPresentacionEmbedding × ProductoPresentacion × Producto ×
CategoriaProducto`` and filter on ``CategoriaProducto.id_comercio ==
id_comercio`` so other comercios are never counted. The
``joinedload`` on the parent relationship is reused so the per-row
``list_by_comercio`` query does not trigger N+1 fetches.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    EmbeddingStatus,
    Producto,
    ProductoPresentacion,
    ProductoPresentacionEmbedding,
)
from backend.repositories.producto_presentacion_embedding_repository import (
    ProductoPresentacionEmbeddingRepository,
)


@dataclass(frozen=True)
class EmbeddingStatusCounts:
    """Per-status and aggregated counters for one comercio and model."""

    pending: int = 0
    ready: int = 0
    failed: int = 0
    stale: int = 0
    inactive: int = 0
    total: int = 0
    active: int = 0
    with_last_error: int = 0


@dataclass(frozen=True)
class EmbeddingSourceTypeCounts:
    """Per-source-type counters for one comercio and model."""

    canonical: int = 0
    description: int = 0
    alias: int = 0
    combined: int = 0


class ProductoPresentacionEmbeddingStatusRepository:
    """Read-only aggregation surface for the local-admin status endpoint."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count_by_comercio(
        self,
        id_comercio: int,
        modelo: str,
    ) -> EmbeddingStatusCounts:
        """Return per-status, total, active, and last-error counts.

        A single ``SELECT`` uses ``func.count().filter(...)`` for every
        status bucket plus the active / last_error aggregates. The JOIN
        through the parent chain scopes the result to the given
        ``comercio_id``.
        """
        stmt = (
            select(
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.embedding_status
                            == EmbeddingStatus.PENDING.value,
                            1,
                        ),
                        else_=None,
                    )
                ).label("pending"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.embedding_status
                            == EmbeddingStatus.READY.value,
                            1,
                        ),
                        else_=None,
                    )
                ).label("ready"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.embedding_status
                            == EmbeddingStatus.FAILED.value,
                            1,
                        ),
                        else_=None,
                    )
                ).label("failed"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.embedding_status
                            == EmbeddingStatus.STALE.value,
                            1,
                        ),
                        else_=None,
                    )
                ).label("stale"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.embedding_status
                            == EmbeddingStatus.INACTIVE.value,
                            1,
                        ),
                        else_=None,
                    )
                ).label("inactive"),
                func.count().label("total"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.activo.is_(True),
                            1,
                        ),
                        else_=None,
                    )
                ).label("active"),
                func.count(
                    case(
                        (
                            ProductoPresentacionEmbedding.last_error.is_not(
                                None
                            ),
                            1,
                        ),
                        else_=None,
                    )
                ).label("with_last_error"),
            )
            .select_from(ProductoPresentacionEmbedding)
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
        )
        row = self._session.execute(stmt).one()
        return EmbeddingStatusCounts(
            pending=int(row.pending or 0),
            ready=int(row.ready or 0),
            failed=int(row.failed or 0),
            stale=int(row.stale or 0),
            inactive=int(row.inactive or 0),
            total=int(row.total or 0),
            active=int(row.active or 0),
            with_last_error=int(row.with_last_error or 0),
        )

    def count_by_source_type(
        self,
        id_comercio: int,
        modelo: str,
    ) -> EmbeddingSourceTypeCounts:
        """Return per-source-type counts for one comercio and model.

        A single ``SELECT`` with ``GROUP BY source_type`` produces the
        raw counts; any source_type bucket with no rows is returned as
        ``0`` so the response shape is always stable.
        """
        stmt = (
            select(
                ProductoPresentacionEmbedding.source_type,
                func.count().label("count"),
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
            .where(
                CategoriaProducto.id_comercio == id_comercio,
                ProductoPresentacionEmbedding.modelo == modelo,
            )
            .group_by(ProductoPresentacionEmbedding.source_type)
        )
        rows = self._session.execute(stmt).all()
        counts = {
            "canonical": 0,
            "description": 0,
            "alias": 0,
            "combined": 0,
        }
        for source_type, count in rows:
            if source_type in counts:
                counts[source_type] = int(count or 0)
        return EmbeddingSourceTypeCounts(
            canonical=counts["canonical"],
            description=counts["description"],
            alias=counts["alias"],
            combined=counts["combined"],
        )

    def list_by_comercio(
        self,
        id_comercio: int,
        modelo: str,
    ) -> list[ProductoPresentacionEmbedding]:
        """Return the underlying rows for the given comercio and model.

        Thin wrapper that reuses the existing 4.6 parent-chain join and
        ``joinedload`` so the per-presentation breakdown has no N+1.
        """
        return ProductoPresentacionEmbeddingRepository(
            self._session
        ).list_by_comercio(id_comercio, modelo)


__all__ = [
    "EmbeddingSourceTypeCounts",
    "EmbeddingStatusCounts",
    "ProductoPresentacionEmbeddingStatusRepository",
]
