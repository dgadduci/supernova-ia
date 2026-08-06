## Why

Subphases 4.6, 4.7, and 4.8 produced a per-document `producto_presentacion_embeddings`
table that already stores pgvector vectors for every `canonical`,
`description`, `alias`, and `combined` document, but the system currently
has no way to ask the database "give me the closest product-presentations
to this query vector for one commerce". Without that surface the
recognizer cannot benefit from the embedding work, and the embeddings
remain a write-only pipeline.

This subphase adds the missing read path: a thin, typed
`ProductPresentationVectorSearcher` that performs a
`pgvector`-backed similarity search over the existing rows, returns the
best matching document per `producto_presentacion`, and isolates the
result by `comercio`. The new surface is the foundation that the
recognizer (and future catalog-aware hybrid routing) will sit on, but it
does not yet connect to the recognizer or the customer-message flow.

## What Changes

- Add `ProductPresentationVectorSearchService` exposing
  `search_similar(*, id_comercio, query_embedding, top_k,
  candidate_producto_presentacion_ids=None)` returning a typed
  `list[ProductPresentationVectorMatch]` ordered from most to least
  similar, with `top_k` applied after collapsing to one match per
  `id_producto_presentacion`.
- The service SHALL execute `search_similar` in this exact order:
  (1) validate `top_k > 0` (raise `InvalidVectorSearchTopK` otherwise),
  (2) validate `len(query_embedding) == settings.embedding_dimension`
  (raise `InvalidVectorSearchDimension` otherwise),
  (3) short-circuit with `[]` when
  `candidate_producto_presentacion_ids == []`, and
  (4) invoke the repository. The empty-candidate-list short-circuit
  SHALL NOT bypass steps 1 or 2: invalid `top_k` and invalid dimension
  still raise even when the candidate list is empty.
- Add a new `ProductoPresentacionEmbeddingSearchRepository` whose ONLY
  SQL surface is a single pgvector distance query against
  `producto_presentacion_embeddings` joined to the parent chain, with
  commerce isolation enforced through `CategoriaProducto.id_comercio`.
- Add a typed result dataclass `ProductPresentationVectorMatch`
  carrying only `id_producto_presentacion`, `score` (1 − cosine
  distance), and `source_type`; vectors, source text, hashes, error
  strings, and internal exception traces are never exposed.
- Add two domain exceptions — `InvalidVectorSearchDimension` and
  `InvalidVectorSearchTopK` — raised before any SQL is issued.
- Add focused tests covering the 15 minimum tests the project playbook
  requires (ordering, commerce isolation, activity chain, embedding
  status, model isolation, dimension / top-k validation, candidate
  restriction, grouping, no-leak checks, and 4.6–4.8 regression), plus
  the new validation-order tests that exercise the fixed order
  (top_k wins over dimension, dimension wins over empty candidate).
- No changes to the 4.6 indexer / seeder / persistence / pure builder,
  the 4.7 admin endpoints, or the 4.8 sync service. No HNSW / IVFFlat
  index migration; exact search is acceptable for the current
  development-scale catalog.

## Capabilities

### New Capabilities

- `product-presentation-vector-search`: pgvector-backed similarity
  search over `producto_presentacion_embeddings` returning the best
  matching document per `producto_presentacion`, isolated by
  `comercio`, with dimension and `top_k` validation, optional candidate
  filtering, and a typed result shape that excludes internal data.

### Modified Capabilities

None. Subphase 4.9 only adds a read path; the 4.6 persistence,
4.7 admin endpoints, and 4.8 sync requirements are explicitly unchanged.

## Impact

- New code:
  - `backend/repositories/producto_presentacion_embedding_search_repository.py`
  - `backend/services/product_presentation_vector_search_service.py`
  - `backend/services/product_presentation_vector_match.py` (result
    dataclass)
  - Two new exception classes in `backend/services/exceptions.py`
    (`InvalidVectorSearchDimension`, `InvalidVectorSearchTopK`)
  - `backend/tests/test_product_presentation_vector_search_service.py`
  - `backend/tests/test_product_presentation_vector_search_module_boundaries.py`
- Touched code:
  - `backend/services/exceptions.py` — two new exception classes.
- No changes to: `backend/models/*`, `backend/alembic/versions/*`,
  `backend/embeddings/*`, `backend/routers/admin_product_embeddings.py`,
  any 4.6 / 4.7 / 4.8 module, the CLI, the indexer, the seeder, the
  document builder, the embedding client, or the settings.
- No new dependencies. The pgvector package is already a project
  dependency (used by the 4.6 persistence model).
- No migration. The vector column already exists; the existing
  `(id_producto_presentacion, modelo)` index supports the exact-search
  query plan and HNSW / IVFFlat are out of scope for the current
  catalog size.
- No customer-facing endpoint, no router changes, no CLI surface, no
  background job, no sync integration, no Ollama call.
