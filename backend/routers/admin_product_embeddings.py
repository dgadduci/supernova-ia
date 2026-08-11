"""Local-admin router for the per-document embedding pipeline.

Subphase 4.7 introduces two endpoints:

- ``POST /admin/comercios/{comercio_id}/product-embeddings/reindex``
- ``GET /admin/comercios/{comercio_id}/product-embeddings/status``

Both endpoints are gated behind
``Settings.enable_local_admin_endpoints`` (env var
``ENABLE_LOCAL_ADMIN_ENDPOINTS``, default ``false``). When the flag is
``false`` every route returns ``404`` so the surface is
indistinguishable from a missing route.

The router receives the SQLAlchemy session through
``Depends(get_session)`` (the existing ``backend.dependencies.get_session``
generator, which is the sole owner of ``session.close()`` in its
``finally``). The router's inner transaction boundary is:

- successful real reindex → ``session.commit()`` exactly once;
- ``dry_run=True`` → no commit;
- unhandled exception → ``session.rollback()`` exactly once, then
  re-raise so FastAPI returns the default ``500`` response.

The router MUST NOT call ``session.close()``. The router MUST NOT
import SQLAlchemy, the embedding client, the indexer, the seeder, the
repositories, or any script. The only call into business logic goes
through :class:`ProductoPresentacionEmbeddingAdminService`.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.product_embedding_admin import (
    PerPresentationOutcome,
    ProductEmbeddingCounters,
    ProductEmbeddingReindexRequest,
    ProductEmbeddingReindexResponse,
    ProductEmbeddingSourceTypeCounts,
    ProductEmbeddingStatusCounts,
    ProductEmbeddingStatusResponse,
)
from backend.services.exceptions import (
    ComercioNotFound,
    InvalidBatchSize,
    InvalidProductEmbeddingAdminScope,
)
from backend.services.producto_presentacion_embedding_admin_service import (
    ProductoPresentacionEmbeddingAdminService,
)
from backend.services.producto_presentacion_embedding_seeder import (
    SeedingOutcome,
    SeedingResult,
)

router = APIRouter(
    tags=["admin-product-embeddings"],
    dependencies=[Depends(require_admin_token)],
)


def _gate_enabled() -> bool:
    """Return the current value of ``Settings.enable_local_admin_endpoints``.

    Reading through ``load_settings()`` keeps the gate in sync with the
    rest of the codebase's settings-loading path. The router
    short-circuits to ``404`` when this returns ``False`` so the admin
    surface is indistinguishable from a missing route.
    """
    return load_settings().enable_local_admin_endpoints


def _build_reindex_response(
    *,
    comercio_id: int,
    payload: ProductEmbeddingReindexRequest,
    result: SeedingResult,
) -> ProductEmbeddingReindexResponse:
    return ProductEmbeddingReindexResponse(
        comercio_id=comercio_id,
        producto_id=payload.producto_id,
        producto_presentacion_id=payload.producto_presentacion_id,
        force=payload.force,
        dry_run=payload.dry_run,
        counters=ProductEmbeddingCounters(
            created=result.created,
            updated=result.updated,
            unchanged=result.unchanged,
            stale=result.stale,
            inactive=result.inactive,
            failed=result.failed,
        ),
        outcomes=[_to_outcome(outcome) for outcome in result.outcomes],
    )


def _to_outcome(outcome: SeedingOutcome) -> PerPresentationOutcome:
    return PerPresentationOutcome(
        id_producto_presentacion=outcome.id_producto_presentacion,
        status=outcome.status,
        reason=outcome.reason,
        created=outcome.created,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        stale=outcome.stale,
        inactive=outcome.inactive,
        failed=outcome.failed,
    )


@router.post(
    "/admin/comercios/{comercio_id}/product-embeddings/reindex",
    response_model=ProductEmbeddingReindexResponse,
)
def post_reindex(
    comercio_id: int,
    payload: ProductEmbeddingReindexRequest,
    session: Annotated[Any, Depends(get_session)],
    _enabled: bool = Depends(_gate_enabled),
) -> ProductEmbeddingReindexResponse:
    if not _enabled:
        raise HTTPException(status_code=404, detail="not found")
    service = ProductoPresentacionEmbeddingAdminService(session)
    try:
        result = service.run_reindex(
            id_comercio=comercio_id,
            id_producto=payload.producto_id,
            id_producto_presentacion=payload.producto_presentacion_id,
            force=payload.force,
            dry_run=payload.dry_run,
            batch_size=payload.batch_size,
        )
        if not payload.dry_run:
            session.commit()
    except ComercioNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidProductEmbeddingAdminScope as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidBatchSize as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    return _build_reindex_response(
        comercio_id=comercio_id,
        payload=payload,
        result=result,
    )


@router.get(
    "/admin/comercios/{comercio_id}/product-embeddings/status",
    response_model=ProductEmbeddingStatusResponse,
)
def get_status(
    comercio_id: int,
    session: Annotated[Any, Depends(get_session)],
    _enabled: bool = Depends(_gate_enabled),
) -> ProductEmbeddingStatusResponse:
    if not _enabled:
        raise HTTPException(status_code=404, detail="not found")
    service = ProductoPresentacionEmbeddingAdminService(session)
    try:
        counts, source_type_counts, _rows = service.get_status(
            id_comercio=comercio_id
        )
    except ComercioNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    settings = load_settings()
    return ProductEmbeddingStatusResponse(
        comercio_id=comercio_id,
        embedding_model=settings.embedding_model,
        embedding_dimension=settings.embedding_dimension,
        total=counts.total,
        counts=ProductEmbeddingStatusCounts(
            pending=counts.pending,
            ready=counts.ready,
            failed=counts.failed,
            stale=counts.stale,
            inactive=counts.inactive,
        ),
        active=counts.active,
        with_last_error=counts.with_last_error,
        source_type_counts=ProductEmbeddingSourceTypeCounts(
            canonical=source_type_counts.canonical,
            description=source_type_counts.description,
            alias=source_type_counts.alias,
            combined=source_type_counts.combined,
        ),
    )


__all__ = ["router"]
