"""Per-document seeder wrapper.

Subphase 4.6 introduces a ``ProductoPresentacionEmbeddingSeeder``
that wraps the indexer and returns a ``SeedingResult`` carrying
``(created, updated, unchanged, stale, inactive, failed)`` aggregate
counts plus a per-presentation ``SeedingOutcome`` list.

The seeder does NOT call ``session.commit()``, ``session.rollback()``,
or ``session.close()``. The CLI is the only owner of those calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.services.producto_presentacion_embedding_indexer import (
    IndexingResult,
    ProductoPresentacionEmbeddingIndexer,
)


@dataclass(frozen=True)
class SeedingOutcome:
    """Per-presentation reconciliation outcome surfaced to the CLI."""

    id_producto_presentacion: int
    status: str
    reason: str | None = None
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    inactive: int = 0
    failed: int = 0


@dataclass(frozen=True)
class SeedingResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    inactive: int = 0
    failed: int = 0
    outcomes: tuple[SeedingOutcome, ...] = field(default_factory=tuple)


class ProductoPresentacionEmbeddingSeeder:
    def __init__(self, indexer: ProductoPresentacionEmbeddingIndexer) -> None:
        self._indexer = indexer

    def run(
        self,
        session: Session,
        *,
        id_comercio: int | None = None,
        id_producto: int | None = None,
        id_producto_presentacion: int | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> SeedingResult:
        result = self._indexer.index_presentations(
            id_comercio=id_comercio,
            id_producto=id_producto,
            id_producto_presentacion=id_producto_presentacion,
            force=force,
            dry_run=dry_run,
        )
        return _to_seeding_result(result)


def _to_seeding_result(result: IndexingResult) -> SeedingResult:
    created = 0
    updated = 0
    unchanged = 0
    stale = 0
    inactive = 0
    failed = 0
    outcomes: list[SeedingOutcome] = []
    for outcome in result.outcomes:
        outcomes.append(
            SeedingOutcome(
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
        )
        created += outcome.created
        updated += outcome.updated
        unchanged += outcome.unchanged
        stale += outcome.stale
        inactive += outcome.inactive
        failed += outcome.failed
    return SeedingResult(
        created=created,
        updated=updated,
        unchanged=unchanged,
        stale=stale,
        inactive=inactive,
        failed=failed,
        outcomes=tuple(outcomes),
    )


__all__ = [
    "ProductoPresentacionEmbeddingSeeder",
    "SeedingOutcome",
    "SeedingResult",
]
