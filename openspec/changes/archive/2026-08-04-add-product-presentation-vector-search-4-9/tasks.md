## 1. Foundation — result dataclass and exceptions

- [x] 1.1 Add `ProductPresentationVectorMatch` frozen dataclass in
  `backend/services/product_presentation_vector_match.py` with exactly
  three fields: `id_producto_presentacion: int`, `score: float`,
  `source_type: str`. Re-export it from `backend/services/__init__.py`
  (or update the existing module map if the package uses symbol
  exports).
- [x] 1.2 Add `InvalidVectorSearchDimension(ValueError)` and
  `InvalidVectorSearchTopK(ValueError)` to
  `backend/services/exceptions.py`. Both subclasses MUST be
  independent of the existing `InvalidBatchSize` /
  `InvalidProductoPresentacionEmbedding` exceptions so the search
  path has its own domain error vocabulary.

## 2. Search repository — single SQL pgvector query

- [x] 2.1 Create
  `backend/repositories/producto_presentacion_embedding_search_repository.py`
  with the `ProductoPresentacionEmbeddingSearchRepository` class.
  Constructor takes `session: Session` and stores it.
- [x] 2.2 Implement `search_similar(*, id_comercio, query_embedding,
  modelo, top_k, candidate_ids=None) -> list[RowMapping]` that
  builds the single pgvector query described in the spec's
  "Repository performs the pgvector distance query" requirement:
  joins `ProductoPresentacionEmbedding` × `ProductoPresentacion`
  × `Producto` × `CategoriaProducto` × `Presentacion`, filters on
  `id_comercio`, `modelo`, `embedding_status='ready'`, the activity
  chain, optional `candidate_ids`, then wraps the result in a
  `ROW_NUMBER() OVER (PARTITION BY id_producto_presentacion ORDER BY
  distance ASC)` subquery and filters on `row_number = 1` with
  `LIMIT top_k`. The query returns `(id_producto_presentacion,
  source_type, score)` ordered by `score DESC` then
  `id_producto_presentacion ASC`.
- [x] 2.3 Confirm the repository module does NOT import or call
  `session.commit()`, `session.rollback()`, `session.close()`, or
  `session.begin()`, and does NOT issue `INSERT`, `UPDATE`, or
  `DELETE` statements. Document the read-only contract in the
  module docstring.

## 3. Search service — validation and result mapping

- [x] 3.1 Create
  `backend/services/product_presentation_vector_search_service.py`
  with the `ProductPresentationVectorSearchService` class.
  Constructor: `__init__(self, session: Session, settings: Settings)`
  stores both and constructs the repository internally.
- [x] 3.2 Implement `search_similar(*, id_comercio, query_embedding,
  top_k, candidate_producto_presentacion_ids=None)`. The method MUST
  execute steps in this exact order, with no other side effects
  between steps:
  (1) raise `InvalidVectorSearchTopK` when `top_k <= 0`;
  (2) raise `InvalidVectorSearchDimension` when
  `len(query_embedding) != settings.embedding_dimension`;
  (3) return `[]` immediately when
  `candidate_producto_presentacion_ids == []`;
  (4) call
  `self._repository.search_similar(id_comercio=id_comercio,
  query_embedding=query_embedding, modelo=settings.embedding_model,
  top_k=top_k, candidate_ids=candidate_producto_presentacion_ids)`;
  (5) map each row to a `ProductPresentationVectorMatch`. The
  empty-candidate-list short-circuit (step 3) MUST NOT bypass steps 1
  or 2; `top_k <= 0` and a wrong-dimension `query_embedding` still
  raise even when the candidate list is empty.
- [x] 3.3 Confirm the service module does NOT import FastAPI, HTTP,
  the embedding client, the document builder, the seeder, the
  indexer, the sync service, the admin router, or any 4.7 schema.
  Document the no-mutation / no-Ollama contract in the module
  docstring.

## 4. Tests — focused search suite

- [x] 4.1 Add
  `backend/tests/test_product_presentation_vector_search_service.py`
  with focused tests covering the 15 scenarios from the project
  playbook plus the validation-order tests:
  1. nearest matches are ordered correctly (best match first,
     deterministic tie-breaker on `id_producto_presentacion ASC`);
  2. results are isolated by `comercio` (rows for other comercios
     are NEVER returned);
  3. inactive products are excluded;
  4. inactive or unavailable `producto_presentaciones` are excluded;
  5. `inactive`, `stale`, `failed`, and `pending` rows are excluded;
  6. embeddings from another model are excluded;
  7. invalid vector dimension is rejected (dimension validation
     happens AFTER the top_k check and BEFORE the empty-candidate
     short-circuit; the repository is NOT invoked);
  8. `top_k <= 0` is rejected (top_k validation happens FIRST; the
     repository is NOT invoked);
  9. candidate IDs restrict results (rows outside
     `candidate_ids` are NEVER returned);
  10. an empty candidate list performs NO database query (the
     short-circuit happens AFTER both validations; the repository is
     NOT invoked and the result is `[]`); exercising the empty
     candidate list with valid `top_k` and a valid `query_embedding`
     returns `[]`;
  11. multiple documents for one product-presentation collapse to
     the best-scoring match;
  12. `top_k` applies to unique product-presentations (10 ready
     rows for 3 unique PPs with `top_k=3` returns 3 PPs);
  13. matched `source_type` corresponds to the winning document
     (the alias document wins → `source_type='alias'`; the canonical
     document wins → `source_type='canonical'`);
  14. no vector or internal data leaks from the service result
     (the returned dataclass exposes only
     `id_producto_presentacion`, `score`, `source_type`);
  15. 4.6–4.8 focused tests remain valid (re-run the existing
     focused test modules after the new code lands);
  16. validation order: `top_k=0` with an empty candidate list
     raises `InvalidVectorSearchTopK` (top_k wins over the empty
     candidate short-circuit);
  17. validation order: a wrong-dimension `query_embedding` with an
     empty candidate list raises `InvalidVectorSearchDimension`
     (dimension wins over the empty candidate short-circuit);
  18. validation order: `top_k=0` with a wrong-dimension
     `query_embedding` raises `InvalidVectorSearchTopK` (top_k wins
     over dimension).
- [x] 4.2 Add
  `backend/tests/test_product_presentation_vector_search_module_boundaries.py`
  with module-boundary tests covering:
  - the service does not import the embedding client, the document
    builder, the seeder, the indexer, the sync service, the admin
    router, or any 4.7 schema;
  - the repository does not import FastAPI, HTTP, the embedding
    client, the document builder, the seeder, the indexer, the
    sync service, or any router;
  - the service and repository do not call `session.commit()`,
    `session.rollback()`, `session.close()`, or `session.begin()`;
  - the result dataclass is frozen and exposes only the three
    documented fields.

## 5. Validation and final report

- [x] 5.1 Run `python -m compileall backend/services/product_presentation_vector_match.py
  backend/services/product_presentation_vector_search_service.py
  backend/repositories/producto_presentacion_embedding_search_repository.py
  backend/tests/test_product_presentation_vector_search_service.py
  backend/tests/test_product_presentation_vector_search_module_boundaries.py`
  and confirm a clean exit.
- [x] 5.2 Run `ruff check backend/services/product_presentation_vector_match.py
  backend/services/product_presentation_vector_search_service.py
  backend/repositories/producto_presentacion_embedding_search_repository.py
  backend/tests/test_product_presentation_vector_search_service.py
  backend/tests/test_product_presentation_vector_search_module_boundaries.py`
  and fix any reported issues.
- [x] 5.3 Run `mypy --strict backend/services/product_presentation_vector_match.py
  backend/services/product_presentation_vector_search_service.py
  backend/repositories/producto_presentacion_embedding_search_repository.py`
  (using the project's existing strict mypy config) and fix any
  reported errors.
- [x] 5.4 Run the focused 4.9 search test modules and the existing
  4.6, 4.7, 4.8 focused test modules; confirm the new tests pass
  AND the 4.6–4.8 tests stay green.
- [x] 5.5 Run `openspec validate
  add-product-presentation-vector-search-4-9 --strict` and confirm
  the change validates cleanly. The OpenSpec change identifier is
  `add-product-presentation-vector-search-4-9` (the kebab-case
  folder name is the single source of truth — no alternate
  identifier is accepted).
- [x] 5.6 Report files changed, exact search operator used,
  validation behavior, tests executed and results, and explicitly
  state whether a vector-index migration was performed (no —
  exact search is acceptable for the current catalog).
