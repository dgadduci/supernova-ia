"""Per-document indexer that reconciles the embedding catalog.

Subphase 4.6 introduces a per-document indexer that walks every
applicable ``producto_presentacion`` (active and inactive), produces
the deterministic documents through the pure
``ProductEmbeddingDocumentBuilder``, and reconciles them against the
persisted rows through the service's
``create_or_update_document(...)`` / ``record_failed_document(...)`` /
``mark_status(...)`` surface.

The indexer does NOT call ``commit``, ``rollback``, ``close``, or
``begin`` anywhere. The CLI is the only owner of those calls.

Batching is precise: the indexer partitions the documents requiring
generation into batches of ``settings.embedding_batch_size``
(the per-run override when ``--batch-size`` is supplied, otherwise the
loaded default). For each batch, the indexer calls
``embedding_client.embed_documents(texts)`` exactly once. The returned
vectors are mapped back to documents by position. If a batch raises
``EmbeddingClientError``, every document in the failing batch
transitions to ``failed`` through ``record_failed_document(...)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.config.settings import Settings
from backend.embeddings import (
    InvalidProductEmbeddingDocument,
    ProductEmbeddingCatalogProjection,
    ProductEmbeddingDocument,
    ProductEmbeddingDocumentBuilder,
)
from backend.llm.embedding_client import (
    EmbeddingClientError,
    EmbeddingClientProtocol,
)
from backend.models import EmbeddingStatus
from backend.repositories.producto_presentacion_embedding_index_repository import (
    PresentationBundle,
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)

_INDEXER_STATUSES_FOR_STALE: frozenset[str] = frozenset(
    {EmbeddingStatus.READY.value, EmbeddingStatus.FAILED.value}
)


@dataclass(frozen=True)
class IndexingOutcome:
    """Per-presentation reconciliation outcome."""

    id_producto_presentacion: int
    status: str
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    stale: int = 0
    inactive: int = 0
    failed: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class IndexingResult:
    """Aggregate reconciliation outcome."""

    completed: int = 0
    failed: int = 0
    outcomes: tuple[IndexingOutcome, ...] = field(default_factory=tuple)


class ProductoPresentacionEmbeddingIndexer:
    def __init__(
        self,
        session: Session,
        embedding_client: EmbeddingClientProtocol,
        embedding_service: ProductoPresentacionEmbeddingService,
        index_repository: ProductoPresentacionEmbeddingIndexRepository,
        settings: Settings,
    ) -> None:
        self._session = session
        self._embedding_client = embedding_client
        self._embedding_service = embedding_service
        self._index_repository = index_repository
        self._settings = settings
        self._builder = ProductEmbeddingDocumentBuilder()

    def index_presentations(
        self,
        *,
        id_comercio: int | None = None,
        id_producto: int | None = None,
        id_producto_presentacion: int | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> IndexingResult:
        bundles = self._index_repository.list_presentations(
            id_comercio=id_comercio,
            id_producto=id_producto,
            id_producto_presentacion=id_producto_presentacion,
        )
        outcomes: list[IndexingOutcome] = []
        completed = 0
        failed = 0
        for bundle in bundles:
            outcome = self._index_one(
                bundle,
                force=force,
                dry_run=dry_run,
            )
            outcomes.append(outcome)
            if outcome.status == "failed":
                failed += 1
            else:
                completed += 1
        return IndexingResult(
            completed=completed,
            failed=failed,
            outcomes=tuple(outcomes),
        )

    def _index_one(
        self,
        bundle: PresentationBundle,
        *,
        force: bool,
        dry_run: bool,
    ) -> IndexingOutcome:
        if bundle.is_inactive():
            return self._mark_inactive(bundle, dry_run=dry_run)
        try:
            documents = self._build_documents(bundle)
        except InvalidProductEmbeddingDocument as exc:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="failed",
                failed=len(self._existing_documents(bundle)),
                reason=str(exc),
            )
        document_tuples = {
            (doc.source_type, doc.source_record_id) for doc in documents
        }
        stale_outcome = self._mark_stale_documents(
            bundle, document_tuples, dry_run=dry_run
        )
        if not documents:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="indexed",
                created=0,
                updated=0,
                unchanged=0,
                stale=stale_outcome,
                inactive=0,
                failed=0,
            )
        outcome = self._generate_documents(
            bundle,
            documents,
            force=force,
            dry_run=dry_run,
        )
        if outcome.status == "failed":
            return outcome
        return IndexingOutcome(
            id_producto_presentacion=bundle.producto_presentacion_id,
            status=outcome.status,
            created=outcome.created,
            updated=outcome.updated,
            unchanged=outcome.unchanged,
            stale=stale_outcome + outcome.stale,
            inactive=outcome.inactive,
            failed=outcome.failed,
            reason=outcome.reason,
        )

    def _build_documents(
        self, bundle: PresentationBundle
    ) -> list[ProductEmbeddingDocument]:
        projection = ProductEmbeddingCatalogProjection(
            producto_id=bundle.producto_id,
            producto_presentacion_id=bundle.producto_presentacion_id,
            producto_nombre=bundle.producto_nombre,
            producto_descripcion=bundle.producto_descripcion,
            categoria_nombre=bundle.categoria_nombre,
            presentacion_id=bundle.presentacion_id,
            presentacion_codigo=bundle.presentacion_codigo,
            presentacion_descripcion=bundle.presentacion_descripcion,
        )
        return self._builder.build(projection, bundle.aliases)

    def _existing_documents(self, bundle: PresentationBundle) -> list[tuple[str, int | None]]:
        rows = self._embedding_service.list_by_producto_presentacion_and_model(
            id_producto_presentacion=bundle.producto_presentacion_id,
            modelo=self._settings.embedding_model,
        )
        return [
            (row.source_type, row.source_record_id) for row in rows
        ]

    def _mark_inactive(
        self, bundle: PresentationBundle, *, dry_run: bool
    ) -> IndexingOutcome:
        rows = self._embedding_service.list_by_producto_presentacion_and_model(
            id_producto_presentacion=bundle.producto_presentacion_id,
            modelo=self._settings.embedding_model,
        )
        if dry_run:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="inactive",
                inactive=len(rows),
            )
        for row in rows:
            self._embedding_service.mark_inactive(row)
        return IndexingOutcome(
            id_producto_presentacion=bundle.producto_presentacion_id,
            status="inactive",
            inactive=len(rows),
        )

    def _mark_stale_documents(
        self,
        bundle: PresentationBundle,
        valid_tuples: set[tuple[Any, Any]],
        *,
        dry_run: bool,
    ) -> int:
        rows = self._embedding_service.list_by_producto_presentacion_and_model(
            id_producto_presentacion=bundle.producto_presentacion_id,
            modelo=self._settings.embedding_model,
        )
        stale_count = 0
        for row in rows:
            if row.embedding_status not in _INDEXER_STATUSES_FOR_STALE:
                continue
            key = (row.source_type, row.source_record_id)
            if key in valid_tuples:
                continue
            if dry_run:
                stale_count += 1
                continue
            self._embedding_service.mark_stale(row)
            stale_count += 1
        return stale_count

    def _generate_documents(
        self,
        bundle: PresentationBundle,
        documents: list[ProductEmbeddingDocument],
        *,
        force: bool,
        dry_run: bool,
    ) -> IndexingOutcome:
        pending = self._classify_pending(bundle, documents, force=force)
        pending_documents: list[ProductEmbeddingDocument] = pending["documents"]
        unchanged_total = pending["unchanged"]
        created_total = 0
        updated_total = 0
        failed_total = 0
        if not pending_documents:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="indexed",
                created=0,
                updated=0,
                unchanged=unchanged_total,
            )
        if dry_run:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="indexed",
                created=pending["created"],
                updated=pending["updated"],
                unchanged=unchanged_total,
            )
        batch_size = self._settings.embedding_batch_size
        if batch_size <= 0:
            return IndexingOutcome(
                id_producto_presentacion=bundle.producto_presentacion_id,
                status="failed",
                failed=0,
                reason="configured embedding batch size must be positive",
            )
        total = len(pending_documents)
        for offset in range(0, total, batch_size):
            batch = pending_documents[offset : offset + batch_size]
            texts = [doc.source_text for doc in batch]
            try:
                vectors = self._embedding_client.embed_documents(texts)
            except EmbeddingClientError as exc:
                for doc in batch:
                    self._embedding_service.record_failed_document(
                        doc,
                        str(exc),
                        modelo=self._settings.embedding_model,
                    )
                    failed_total += 1
                continue
            if len(vectors) != len(batch):
                err = (
                    f"embedding client returned {len(vectors)} vectors "
                    f"for batch of {len(batch)} documents"
                )
                for doc in batch:
                    self._embedding_service.record_failed_document(
                        doc,
                        err,
                        modelo=self._settings.embedding_model,
                    )
                    failed_total += 1
                continue
            for doc, vector in zip(batch, vectors):
                outcome = self._embedding_service.create_or_update_document(
                    doc,
                    vector,
                    modelo=self._settings.embedding_model,
                    force=force,
                )
                if outcome == "created":
                    created_total += 1
                elif outcome == "updated":
                    updated_total += 1
                else:
                    unchanged_total += 1
        return IndexingOutcome(
            id_producto_presentacion=bundle.producto_presentacion_id,
            status="indexed",
            created=created_total,
            updated=updated_total,
            unchanged=unchanged_total,
            failed=failed_total,
        )

    def _classify_pending(
        self,
        bundle: PresentationBundle,
        documents: list[ProductEmbeddingDocument],
        *,
        force: bool,
    ) -> dict[str, Any]:
        existing = self._embedding_service.list_by_producto_presentacion_and_model(
            id_producto_presentacion=bundle.producto_presentacion_id,
            modelo=self._settings.embedding_model,
        )
        existing_by_tuple = {
            (row.source_type, row.source_record_id): row for row in existing
        }
        pending: list[ProductEmbeddingDocument] = []
        created = 0
        updated = 0
        unchanged = 0
        for doc in documents:
            row = existing_by_tuple.get((doc.source_type, doc.source_record_id))
            if row is None:
                pending.append(doc)
                created += 1
                continue
            if (
                not force
                and row.content_hash == doc.content_hash
                and row.embedding_status == EmbeddingStatus.READY.value
                and row.activo is True
                and row.vector is not None
                and len(row.vector) == self._settings.embedding_dimension
            ):
                unchanged += 1
                continue
            pending.append(doc)
            updated += 1
        return {
            "documents": pending,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }


__all__ = [
    "IndexingOutcome",
    "IndexingResult",
    "ProductoPresentacionEmbeddingIndexer",
]
