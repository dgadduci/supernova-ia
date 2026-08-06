"""pgvector-backed product-presentation similarity search service.

Subphase 4.9 introduces a thin, typed search service that exposes the
read path over the existing 4.6 ``producto_presentacion_embeddings``
table. The service:

- Owns the validation surface (``top_k``, ``query_embedding`` length
  against ``Settings.embedding_dimension``, and the empty-candidate
  short-circuit) and the result mapping into the typed
  :class:`ProductPresentationVectorMatch`.
- Delegates the single pgvector cosine-distance query to the
  read-only :class:`ProductoPresentacionEmbeddingSearchRepository`.
- NEVER calls :meth:`Session.commit`, :meth:`Session.rollback`,
  :meth:`Session.close`, or :meth:`Session.begin`. The caller owns
  the transaction boundary.
- NEVER imports FastAPI, HTTP, the embedding client, the document
  builder, the seeder, the indexer, the sync service, the admin
  router, or any 4.7 schema. The service is a sibling of those
  modules — it does NOT depend on them.
- NEVER mutates a ``producto_presentacion_embeddings`` row. The
  service is a read-only consumer of the existing pipeline.
- NEVER calls ``OllamaEmbeddingClient.embed_query`` / ``embed_documents``
  or any text normalization helper. ``query_embedding`` arrives
  pre-computed; the service is a pure SQL consumer.

The validation order is fixed:

1. If ``top_k <= 0`` raise :class:`InvalidVectorSearchTopK`.
2. Else if ``len(query_embedding) != settings.embedding_dimension``
   raise :class:`InvalidVectorSearchDimension`.
3. Else if ``candidate_producto_presentacion_ids == []`` return ``[]``
   immediately without invoking the repository.
4. Else invoke the repository and map the result.

The empty-candidate-list short-circuit (step 3) MUST NOT bypass steps
1 or 2: invalid ``top_k`` and invalid dimension still raise even when
the candidate list is empty.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from backend.repositories.producto_presentacion_embedding_search_repository import (
    ProductoPresentacionEmbeddingSearchRepository,
)
from backend.services.exceptions import (
    InvalidVectorSearchDimension,
    InvalidVectorSearchTopK,
)
from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)

if TYPE_CHECKING:
    from backend.config.settings import Settings


class ProductPresentationVectorSearchService:
    """Thin typed search surface over the 4.6 embedding table."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        repository: ProductoPresentacionEmbeddingSearchRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repository = (
            repository
            if repository is not None
            else ProductoPresentacionEmbeddingSearchRepository(session)
        )

    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding: Sequence[float],
        top_k: int,
        candidate_producto_presentacion_ids: Sequence[int] | None = None,
    ) -> list[ProductPresentationVectorMatch]:
        """Return the best matching presentation per ``id_producto_presentacion``.

        Raises :class:`InvalidVectorSearchTopK` when ``top_k <= 0``,
        :class:`InvalidVectorSearchDimension` when ``len(query_embedding)
        != settings.embedding_dimension``. Returns ``[]`` immediately
        when ``candidate_producto_presentacion_ids == []`` AFTER both
        validations pass.

        The repository is NEVER invoked for invalid input or an empty
        candidate list, so no SQL is ever issued in those cases.
        """
        if top_k <= 0:
            raise InvalidVectorSearchTopK(
                "top_k must be a positive integer"
            )
        if len(query_embedding) != self._settings.embedding_dimension:
            raise InvalidVectorSearchDimension(
                "query_embedding length must match Settings.embedding_dimension"
            )
        if (
            candidate_producto_presentacion_ids is not None
            and len(candidate_producto_presentacion_ids) == 0
        ):
            return []
        rows = self._repository.search_similar(
            id_comercio=id_comercio,
            query_embedding=list(query_embedding),
            modelo=self._settings.embedding_model,
            top_k=top_k,
            candidate_ids=(
                list(candidate_producto_presentacion_ids)
                if candidate_producto_presentacion_ids is not None
                else None
            ),
        )
        return [
            ProductPresentationVectorMatch(
                id_producto_presentacion=int(str(row["id_producto_presentacion"])),
                score=float(str(row["score"])),
                source_type=str(row["source_type"]),
            )
            for row in rows
        ]


__all__ = ["ProductPresentationVectorSearchService"]