"""Pydantic request / response shapes for the local-admin embedding endpoints.

Subphase 4.7 introduces the request / response DTOs for
``POST /admin/comercios/{comercio_id}/product-embeddings/reindex`` and
``GET /admin/comercios/{comercio_id}/product-embeddings/status``. The
schemas do NOT validate ``batch_size`` so the rejection surfaces as
``HTTP 400 InvalidBatchSize`` at the router layer instead of
``HTTP 422 pydantic.ValidationError``. The response shapes never
expose embedding vectors, source text, normalized text, content
hashes, or internal exception traces.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProductEmbeddingReindexRequest(BaseModel):
    """JSON body for the reindex endpoint.

    The schema does NOT validate ``batch_size``: the service layer
    raises ``InvalidBatchSize`` for non-positive values so the router
    can map the failure to ``HTTP 400`` instead of the
    ``pydantic.ValidationError`` → ``HTTP 422`` path.
    """

    model_config = ConfigDict(extra="forbid")

    producto_id: int | None = None
    producto_presentacion_id: int | None = None
    force: bool = False
    dry_run: bool = False
    batch_size: int | None = None


class ProductEmbeddingCounters(BaseModel):
    """Aggregate counters exposed in the reindex response."""

    model_config = ConfigDict(extra="forbid")

    created: int
    updated: int
    unchanged: int
    stale: int
    inactive: int
    failed: int


class PerPresentationOutcome(BaseModel):
    """Per-presentation reconciliation outcome surfaced for triage."""

    model_config = ConfigDict(extra="forbid")

    id_producto_presentacion: int
    status: str
    reason: str | None = None
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    inactive: int = 0
    failed: int = 0


class ProductEmbeddingReindexResponse(BaseModel):
    """Response shape for the reindex endpoint."""

    model_config = ConfigDict(extra="forbid")

    comercio_id: int
    producto_id: int | None
    producto_presentacion_id: int | None
    force: bool
    dry_run: bool
    counters: ProductEmbeddingCounters
    outcomes: list[PerPresentationOutcome]


class ProductEmbeddingStatusCounts(BaseModel):
    """Per-status counters in the status response."""

    model_config = ConfigDict(extra="forbid")

    pending: int
    ready: int
    failed: int
    stale: int
    inactive: int


class ProductEmbeddingSourceTypeCounts(BaseModel):
    """Per-source-type counters in the status response."""

    model_config = ConfigDict(extra="forbid")

    canonical: int
    description: int
    alias: int
    combined: int


class ProductEmbeddingStatusResponse(BaseModel):
    """Response shape for the status endpoint."""

    model_config = ConfigDict(extra="forbid")

    comercio_id: int
    embedding_model: str
    embedding_dimension: int
    total: int
    counts: ProductEmbeddingStatusCounts
    active: int
    with_last_error: int
    source_type_counts: ProductEmbeddingSourceTypeCounts


__all__ = [
    "PerPresentationOutcome",
    "ProductEmbeddingCounters",
    "ProductEmbeddingReindexRequest",
    "ProductEmbeddingReindexResponse",
    "ProductEmbeddingSourceTypeCounts",
    "ProductEmbeddingStatusCounts",
    "ProductEmbeddingStatusResponse",
]
