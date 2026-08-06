"""Local-admin service for the per-document embedding pipeline.

Subphase 4.7 introduces a small admin-facing service that owns the
``OllamaEmbeddingClient`` (constructor signature unchanged),
``ProductoPresentacionEmbeddingIndexer``, and
``ProductoPresentacionEmbeddingSeeder`` for the HTTP path. The
service is the single owner of the HTTP-side construction, the
``dataclasses.replace(settings, embedding_batch_size=...)`` override
on the frozen ``Settings``, and the input validation that maps the
Pydantic request shape to the indexer's public API.

The service:

- Validates ``comercio_id`` through ``ComercioService.get_by_id(...)``
  (raises ``ComercioNotFound``).
- Validates that optional ``producto_id`` / ``producto_presentacion_id``
  belong to the comercio through the existing 4.6 parent-chain
  projection (raises ``InvalidProductEmbeddingAdminScope`` when they do
  not).
- Validates that ``batch_size`` is a positive integer when supplied
  (raises ``InvalidBatchSize``). The Pydantic request schema does NOT
  validate ``batch_size`` so the rejection surfaces as ``HTTP 400``
  instead of ``422``.
- Instantiates ``OllamaEmbeddingClient`` through the existing
  ``(settings, transport=None, clock=None)`` constructor; the
  constructor signature is NOT extended.
- Accepts the ``embedding_client``, ``indexer``, and ``seeder``
  through constructor / factory injection so tests substitute fakes
  without a real Ollama call.

The service MUST NOT import ``sqlalchemy``, ``fastapi``, or ``requests``.
The service MUST NOT call ``commit``, ``rollback``, ``close``, or
``begin`` on its session. The service MUST NOT contain raw SQLAlchemy
queries (those live in the repositories). The transaction boundary
lives in the router.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from backend.config.settings import Settings, load_settings
from backend.llm.embedding_client import (
    EmbeddingClientProtocol,
    OllamaEmbeddingClient,
)
from backend.models import ProductoPresentacionEmbedding
from backend.repositories.producto_presentacion_embedding_index_repository import (
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.repositories.producto_presentacion_embedding_status_repository import (
    EmbeddingSourceTypeCounts,
    EmbeddingStatusCounts,
    ProductoPresentacionEmbeddingStatusRepository,
)
from backend.services.comercio_service import ComercioService
from backend.services.exceptions import (
    InvalidBatchSize,
    InvalidProductEmbeddingAdminScope,
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


class ProductoPresentacionEmbeddingAdminService:
    """Thin admin-facing wrapper over the 4.6 indexer / seeder."""

    def __init__(
        self,
        session: Any,
        *,
        embedding_client: EmbeddingClientProtocol | None = None,
        indexer: ProductoPresentacionEmbeddingIndexer | None = None,
        seeder: ProductoPresentacionEmbeddingSeeder | None = None,
    ) -> None:
        self._session = session
        self._embedding_client = embedding_client
        self._indexer = indexer
        self._seeder = seeder

    def run_reindex(
        self,
        *,
        id_comercio: int,
        id_producto: int | None = None,
        id_producto_presentacion: int | None = None,
        force: bool = False,
        dry_run: bool = False,
        batch_size: int | None = None,
    ) -> SeedingResult:
        """Validate the request and delegate to the 4.6 seeder.

        Raises ``ComercioNotFound`` when ``id_comercio`` does not exist,
        ``InvalidProductEmbeddingAdminScope`` when an optional
        ``id_producto`` / ``id_producto_presentacion`` does not belong
        to the comercio, and ``InvalidBatchSize`` when ``batch_size``
        is not a positive integer.
        """
        self._validate_comercio(id_comercio)
        self._validate_scope(id_comercio, id_producto, id_producto_presentacion)
        effective_settings = self._build_effective_settings(batch_size)
        seeder = self._build_seeder(effective_settings)
        return seeder.run(
            self._session,
            id_comercio=id_comercio,
            id_producto=id_producto,
            id_producto_presentacion=id_producto_presentacion,
            force=force,
            dry_run=dry_run,
        )

    def get_status(
        self,
        *,
        id_comercio: int,
    ) -> tuple[
        EmbeddingStatusCounts,
        EmbeddingSourceTypeCounts,
        list[ProductoPresentacionEmbedding],
    ]:
        """Validate the comercio and delegate to the status repository.

        Raises ``ComercioNotFound`` when ``id_comercio`` does not exist.
        """
        self._validate_comercio(id_comercio)
        settings = load_settings()
        repository = ProductoPresentacionEmbeddingStatusRepository(self._session)
        counts = repository.count_by_comercio(id_comercio, settings.embedding_model)
        source_type_counts = repository.count_by_source_type(
            id_comercio, settings.embedding_model
        )
        rows = repository.list_by_comercio(id_comercio, settings.embedding_model)
        return counts, source_type_counts, rows

    def _validate_comercio(self, id_comercio: int) -> None:
        ComercioService(self._session).get_by_id(id_comercio)

    def _validate_scope(
        self,
        id_comercio: int,
        id_producto: int | None,
        id_producto_presentacion: int | None,
    ) -> None:
        if id_producto is None and id_producto_presentacion is None:
            return
        projection_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        bundles = projection_repository.list_presentations(
            id_comercio=id_comercio,
            id_producto=id_producto,
            id_producto_presentacion=id_producto_presentacion,
        )
        if not bundles:
            raise InvalidProductEmbeddingAdminScope(
                "producto_id / producto_presentacion_id does not belong "
                "to the supplied comercio_id"
            )

    def _build_effective_settings(self, batch_size: int | None) -> Settings:
        base = load_settings()
        if batch_size is None:
            return base
        if not isinstance(batch_size, int) or isinstance(batch_size, bool):
            raise InvalidBatchSize("batch_size must be a positive integer")
        if batch_size <= 0:
            raise InvalidBatchSize("batch_size must be a positive integer")
        return dataclasses.replace(base, embedding_batch_size=batch_size)

    def _build_seeder(
        self,
        effective_settings: Settings,
    ) -> ProductoPresentacionEmbeddingSeeder:
        if self._seeder is not None:
            return self._seeder
        indexer = self._build_indexer(effective_settings)
        return ProductoPresentacionEmbeddingSeeder(indexer)

    def _build_indexer(
        self,
        effective_settings: Settings,
    ) -> ProductoPresentacionEmbeddingIndexer:
        if self._indexer is not None:
            return self._indexer
        embedding_client = self._build_embedding_client(effective_settings)
        index_repository = ProductoPresentacionEmbeddingIndexRepository(
            self._session
        )
        embedding_service = ProductoPresentacionEmbeddingService(self._session)
        return ProductoPresentacionEmbeddingIndexer(
            session=self._session,
            embedding_client=embedding_client,
            embedding_service=embedding_service,
            index_repository=index_repository,
            settings=effective_settings,
        )

    def _build_embedding_client(
        self,
        effective_settings: Settings,
    ) -> EmbeddingClientProtocol:
        if self._embedding_client is not None:
            return self._embedding_client
        return OllamaEmbeddingClient(effective_settings)


__all__ = ["ProductoPresentacionEmbeddingAdminService"]
