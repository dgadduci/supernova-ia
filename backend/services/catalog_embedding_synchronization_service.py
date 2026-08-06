"""Catalog-embedding synchronization service.

Subphase 4.8 introduces ``CatalogEmbeddingSynchronizationService`` to
close the loop between the catalog mutation paths and the existing 4.6
per-document embedding pipeline. The service is a thin orchestrator:

- It accepts the caller's outer ``Session``, a constructed
  ``OllamaEmbeddingClient(settings)`` (the same constructor signature
  the 4.6 / 4.7 code uses; the constructor is NOT extended), and the
  loaded ``Settings``.
- It exposes five scope entry points that map 1:1 to the catalog
  mutation paths:
    - ``synchronize_producto(id_producto)``
    - ``synchronize_producto_presentacion(id_producto_presentacion)``
    - ``synchronize_categoria(id_categoria)``
    - ``synchronize_presentacion(id_presentacion)``
    - ``synchronize_alias(id_alias)``
- It resolves the narrowest valid embedding scope through the
  read-only repository methods
  (``list_producto_presentacion_ids_by_producto``,
  ``list_producto_presentacion_ids_by_categoria``,
  ``list_producto_presentacion_ids_by_presentacion``,
  ``list_producto_presentacion_ids_by_alias``).
- It delegates the regeneration to the existing 4.6
  ``ProductoPresentacionEmbeddingIndexer`` /
  ``ProductoPresentacionEmbeddingSeeder`` public surface using the
  existing scoped filters; it does NOT duplicate document building,
  hash comparison, batching, state transitions, or client
  construction.
- It aggregates the per-call ``SeedingResult`` counters into an
  ``EmbeddingSynchronizationResult`` without reclassifying outcomes.

The service MUST NOT call ``session.commit()``, ``session.rollback()``,
``session.close()``, or ``session.begin()`` on any session it
receives. The router / CLI / orchestrator owns the complete
orchestration sequence (``commit catalog -> sync -> commit or rollback
sync``). The synchronization service is constructed with the caller's
outer ``Session`` and relies on the existing ``get_session`` generator
to close the session.

The service MUST NOT import FastAPI, the admin router, the document
builder internals, or any catalog mutation services. SQLAlchemy reads
for scope resolution live in repositories; the service does NOT issue
``select()`` calls directly.

On an unhandled ``SQLAlchemyError`` the service returns an
``EmbeddingSynchronizationResult`` with ``synchronization_failed=True``
and ``attempted=False`` (every counter ``0``); the caller rolls back
the synchronization transaction and returns the safe result. The
previously committed catalog row is NOT affected.
"""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config.settings import Settings
from backend.llm.embedding_client import EmbeddingClientProtocol
from backend.repositories.producto_presentacion_embedding_index_repository import (
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.services.embedding_synchronization_result import (
    EmbeddingSynchronizationResult,
    empty_result,
    synchronization_failed_result,
)
from backend.services.producto_presentacion_embedding_indexer import (
    ProductoPresentacionEmbeddingIndexer,
)
from backend.services.producto_presentacion_embedding_seeder import (
    ProductoPresentacionEmbeddingSeeder,
    SeedingResult,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)


class CatalogEmbeddingSynchronizationService:
    """Thin orchestrator that drives the 4.6 pipeline after a catalog mutation.

    The service holds the caller's outer ``Session``, an
    ``EmbeddingClientProtocol`` (typically the constructed
    ``OllamaEmbeddingClient(settings)``), the loaded ``Settings``, and
    the 4.6 ``ProductoPresentacionEmbeddingSeeder``. It does NOT issue
    SQLAlchemy writes or transaction lifecycle calls; it delegates the
    regeneration to the existing indexer / seeder and only owns the
    aggregation of the per-call ``SeedingResult`` into the narrower
    ``EmbeddingSynchronizationResult``.
    """

    def __init__(
        self,
        session: Session,
        embedding_client: EmbeddingClientProtocol,
        settings: Settings,
        *,
        indexer: ProductoPresentacionEmbeddingIndexer | None = None,
        seeder: ProductoPresentacionEmbeddingSeeder | None = None,
    ) -> None:
        self._session = session
        self._embedding_client = embedding_client
        self._settings = settings
        if seeder is not None:
            self._seeder = seeder
        elif indexer is not None:
            self._seeder = ProductoPresentacionEmbeddingSeeder(indexer)
        else:
            self._seeder = self._build_default_seeder()

    def _build_default_seeder(self) -> ProductoPresentacionEmbeddingSeeder:
        index_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        embedding_service = ProductoPresentacionEmbeddingService(self._session)
        indexer = ProductoPresentacionEmbeddingIndexer(
            session=self._session,
            embedding_client=self._embedding_client,
            embedding_service=embedding_service,
            index_repository=index_repository,
            settings=self._settings,
        )
        return ProductoPresentacionEmbeddingSeeder(indexer)

    # -- Scope entry points --------------------------------------------------

    def synchronize_producto(
        self, id_producto: int
    ) -> EmbeddingSynchronizationResult:
        """Reindex every presentation of the given producto."""
        scope_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        ids = scope_repository.list_producto_presentacion_ids_by_producto(
            id_producto
        )
        return self._synchronize_ids(ids)

    def synchronize_producto_presentacion(
        self, id_producto_presentacion: int
    ) -> EmbeddingSynchronizationResult:
        """Reindex the single presentation."""
        return self._synchronize_ids([id_producto_presentacion])

    def synchronize_categoria(
        self, id_categoria: int
    ) -> EmbeddingSynchronizationResult:
        """Reindex every presentation whose parent producto belongs to
        the given categoria."""
        scope_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        ids = scope_repository.list_producto_presentacion_ids_by_categoria(
            id_categoria
        )
        return self._synchronize_ids(ids)

    def synchronize_presentacion(
        self, id_presentacion: int
    ) -> EmbeddingSynchronizationResult:
        """Reindex every ``producto_presentacion`` that references the
        given presentacion."""
        scope_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        ids = scope_repository.list_producto_presentacion_ids_by_presentacion(
            id_presentacion
        )
        return self._synchronize_ids(ids)

    def synchronize_alias(
        self, id_alias: int
    ) -> EmbeddingSynchronizationResult:
        """Reindex the affected scope for the given alias.

        For presentation-specific aliases the single
        ``id_producto_presentacion`` is reindexed. For product-wide
        aliases every ``producto_presentacion`` of the alias's
        ``id_producto`` is reindexed.

        NOTE: This entry point is intended for alias create / update
        text / activate / deactivate paths where the alias row still
        exists. The post-delete synchronization uses the captured
        scope with ``synchronize_producto`` or
        ``synchronize_producto_presentacion`` instead.
        """
        scope_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        ids = scope_repository.list_producto_presentacion_ids_by_alias(id_alias)
        return self._synchronize_ids(ids)

    # -- Aggregation ---------------------------------------------------------

    def _synchronize_ids(
        self, id_producto_presentacion_values: list[int]
    ) -> EmbeddingSynchronizationResult:
        if not id_producto_presentacion_values:
            return empty_result()
        try:
            return self._aggregate(
                self._run_for_ids(id_producto_presentacion_values)
            )
        except SQLAlchemyError:
            return synchronization_failed_result()

    def _run_for_ids(
        self, id_producto_presentacion_values: list[int]
    ) -> list[SeedingResult]:
        results: list[SeedingResult] = []
        for pp_id in id_producto_presentacion_values:
            result = self._seeder.run(
                self._session,
                id_producto_presentacion=pp_id,
            )
            results.append(result)
        return results

    def _aggregate(
        self, results: list[SeedingResult]
    ) -> EmbeddingSynchronizationResult:
        created = 0
        updated = 0
        unchanged = 0
        stale = 0
        inactive = 0
        failed = 0
        for result in results:
            created += result.created
            updated += result.updated
            unchanged += result.unchanged
            stale += result.stale
            inactive += result.inactive
            failed += result.failed
        return EmbeddingSynchronizationResult(
            attempted=True,
            created=created,
            updated=updated,
            unchanged=unchanged,
            stale=stale,
            inactive=inactive,
            failed=failed,
            synchronization_failed=False,
        )


__all__ = ["CatalogEmbeddingSynchronizationService"]
