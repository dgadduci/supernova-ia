"""Typed synchronization result for the catalog-embedding pipeline.

Subphase 4.8 introduces the ``EmbeddingSynchronizationResult`` dataclass
that the ``CatalogEmbeddingSynchronizationService`` returns after each
catalog-mutation-driven sync run. The result is intentionally narrow:

- It exposes only the six reconciliation counters produced by the 4.6
  ``ProductoPresentacionEmbeddingSeeder`` (``created``, ``updated``,
  ``unchanged``, ``stale``, ``inactive``, ``failed``) plus two
  orchestration flags (``attempted``, ``synchronization_failed``).
- It never carries embedding vectors, source text, normalized text,
  content hashes, internal exception traces, customer-facing messages,
  or the persisted ``Settings``.

The result is consumed by the catalog mutation router / CLI /
orchestrator to decide whether the catalog row stays committed (the
catalog transaction is already finalised) and how the caller should
surface the sync state to operators. The caller rolls back the
synchronization transaction when ``synchronization_failed`` is True.

The module is intentionally stdlib-only so it can be imported from any
service, router, or test without dragging in SQLAlchemy, FastAPI, the
embedding client, or the persistence layer.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingSynchronizationResult:
    """Aggregate reconciliation outcome of one catalog-mutation sync run.

    ``attempted=False`` is returned only when the caller's scope was
    empty (no affected presentation) or when an unhandled persistence
    or synchronization error prevented any outcome from being produced.

    ``synchronization_failed=True`` is returned when the 4.6 seeder
    produced no recoverable result and the synchronization transaction
    had to roll back. The catalog transaction was already committed by
    the caller and is NOT affected.
    """

    attempted: bool = False
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    inactive: int = 0
    failed: int = 0
    synchronization_failed: bool = False


def empty_result() -> EmbeddingSynchronizationResult:
    """Return the canonical empty-scope result.

    The caller received no affected presentations, so no Ollama call was
    issued, every counter is zero, and the operation is neither a
    failure nor a partial sync.
    """
    return EmbeddingSynchronizationResult(
        attempted=False,
        created=0,
        updated=0,
        unchanged=0,
        stale=0,
        inactive=0,
        failed=0,
        synchronization_failed=False,
    )


def synchronization_failed_result() -> EmbeddingSynchronizationResult:
    """Return the canonical recovery-safe result.

    An unhandled ``SQLAlchemyError`` interrupted the sync before any
    recoverable outcome could be produced. The caller uses this result
    to surface the failure and to roll back ONLY the synchronization
    transaction.
    """
    return EmbeddingSynchronizationResult(
        attempted=False,
        created=0,
        updated=0,
        unchanged=0,
        stale=0,
        inactive=0,
        failed=0,
        synchronization_failed=True,
    )


__all__ = [
    "EmbeddingSynchronizationResult",
    "empty_result",
    "synchronization_failed_result",
]
