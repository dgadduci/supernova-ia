# Capability: product-presentation-vector-search

## Purpose

TBD

## Requirements

### Requirement: Product-presentation vector search service

The system SHALL provide a `ProductPresentationVectorSearchService` in
`backend/services/product_presentation_vector_search_service.py` that
exposes a single read-only entry point:

```python
search_similar(
    *,
    id_comercio: int,
    query_embedding: list[float],
    top_k: int,
    candidate_producto_presentacion_ids: list[int] | None = None,
) -> list[ProductPresentationVectorMatch]
```

The service SHALL accept a SQLAlchemy `Session` and the project's
loaded `Settings` through its constructor. `query_embedding` is the
already-computed vector for the search query; the service SHALL NOT
invoke `OllamaEmbeddingClient` and SHALL NOT call any embedding model
or text normalization helper. The service SHALL NOT call
`session.commit()`, `session.rollback()`, `session.close()`, or
`session.begin()`. The service SHALL NOT import FastAPI, HTTP, the
embedding client, the document builder, the seeder, the indexer, the
sync service, or the admin router. The service SHALL NOT perform
mutation of any `producto_presentacion_embeddings` row.

The service SHALL execute `search_similar` in this exact order, with
no other side effects between steps:

1. If `top_k <= 0`, raise `InvalidVectorSearchTopK` and return
   without invoking any other step.
2. Otherwise, if `len(query_embedding) != settings.embedding_dimension`,
   raise `InvalidVectorSearchDimension` and return without invoking
   any other step.
3. Otherwise, if `candidate_producto_presentacion_ids == []`, return
   `[]` immediately without invoking the repository.
4. Otherwise, invoke the repository to execute the pgvector distance
   query and map the result to `ProductPresentationVectorMatch`.

The candidate-short-circuit (step 3) SHALL NOT bypass steps 1 and 2:
invalid `top_k` and invalid dimension still raise even when the
candidate list is empty. The repository SHALL NEVER be invoked for
invalid input or an empty candidate list, so no SQL is ever issued in
those cases.

The service's only collaborator for SQL is a new
`ProductoPresentacionEmbeddingSearchRepository` that owns the pgvector
distance query and the parent-chain join.

#### Scenario: Service signature is keyword-only

- **WHEN** the service module is inspected
- **THEN** `search_similar` accepts ONLY keyword arguments
  (`id_comercio`, `query_embedding`, `top_k`,
  `candidate_producto_presentacion_ids`) and has no positional
  parameters

#### Scenario: Service does not own commit / rollback / close / begin

- **WHEN** the service module is inspected
- **THEN** the module does NOT import or call `session.commit()`,
  `session.rollback()`, `session.close()`, or `session.begin()`
  anywhere in its source

#### Scenario: Service does not call Ollama

- **WHEN** the service module is inspected
- **THEN** it does NOT import `OllamaEmbeddingClient` or any embedding
  client constructor
- **AND** it does NOT call `embed_documents` or `embed_query`
- **AND** it does NOT import the document builder, the text
  normalization helper, or the seeder

#### Scenario: Service does not import HTTP / router modules

- **WHEN** the service module is inspected
- **THEN** it does NOT import FastAPI, `APIRouter`, `HTTPException`, or
  any router module

#### Scenario: Service does not perform embedding mutations

- **WHEN** the service module is inspected
- **THEN** it does NOT issue `INSERT`, `UPDATE`, or `DELETE` statements
  against `producto_presentacion_embeddings`
- **AND** it does NOT call any `mark_status`, `mark_stale`,
  `mark_inactive`, `record_failed_document`, or
  `create_or_update_document` method

#### Scenario: Empty candidate list short-circuits without SQL

- **WHEN** the service is called with valid `top_k`, valid
  `query_embedding`, and `candidate_producto_presentacion_ids=[]`
- **THEN** the service returns `[]` immediately
- **AND** the repository is NOT invoked
- **AND** no SQL is issued against `producto_presentacion_embeddings`

#### Scenario: Empty candidate list does not bypass top_k validation

- **WHEN** the service is called with `top_k=0` and
  `candidate_producto_presentacion_ids=[]`
- **THEN** the service raises `InvalidVectorSearchTopK`
- **AND** the service does NOT return `[]` for the empty candidate
  list
- **AND** the repository is NOT invoked
- **AND** no SQL is issued against `producto_presentacion_embeddings`

#### Scenario: Empty candidate list does not bypass dimension validation

- **WHEN** the service is called with a wrong-dimension
  `query_embedding` and `candidate_producto_presentacion_ids=[]`
- **THEN** the service raises `InvalidVectorSearchDimension`
- **AND** the service does NOT return `[]` for the empty candidate
  list
- **AND** the repository is NOT invoked
- **AND** no SQL is issued against `producto_presentacion_embeddings`

### Requirement: Top-k and dimension validation

The service SHALL validate `top_k` and `query_embedding` before any
SQL is issued, in this exact order: top_k first, then dimension. The
service SHALL raise `InvalidVectorSearchTopK` (a `ValueError` subclass
defined in `backend/services/exceptions.py`) when `top_k <= 0`. The
service SHALL raise `InvalidVectorSearchDimension` (a `ValueError`
subclass) when the length of `query_embedding` differs from
`Settings.embedding_dimension`. Both validations MUST happen before
the repository is invoked AND before the empty-candidate-list
short-circuit, so a malformed query never reaches the database and
the empty-candidate-list path never silently swallows invalid input.

#### Scenario: Zero top_k is rejected

- **WHEN** `search_similar(top_k=0)` is called with a valid
  `query_embedding`
- **THEN** the service raises `InvalidVectorSearchTopK`
- **AND** the repository is NOT invoked
- **AND** no SQL is issued

#### Scenario: Negative top_k is rejected

- **WHEN** `search_similar(top_k=-1)` is called with a valid
  `query_embedding`
- **THEN** the service raises `InvalidVectorSearchTopK`
- **AND** the repository is NOT invoked
- **AND** no SQL is issued

#### Scenario: Invalid top_k wins over invalid dimension

- **WHEN** `search_similar(top_k=0, query_embedding=<wrong-dimension
  list>)` is called
- **THEN** the service raises `InvalidVectorSearchTopK`
- **AND** the dimension check is NOT performed (or its result is
  shadowed)
- **AND** the repository is NOT invoked

#### Scenario: Invalid dimension wins over empty candidate list

- **WHEN** `search_similar(...)` is called with a valid `top_k`, a
  wrong-dimension `query_embedding`, and
  `candidate_producto_presentacion_ids=[]`
- **THEN** the service raises `InvalidVectorSearchDimension`
- **AND** the empty-candidate-list short-circuit is NOT taken
- **AND** the repository is NOT invoked

#### Scenario: Query dimension mismatch is rejected

- **WHEN** `search_similar(query_embedding=[0.1, 0.2], ...)` is called
  with a valid `top_k` and `Settings.embedding_dimension != 2`
- **THEN** the service raises `InvalidVectorSearchDimension`
- **AND** the repository is NOT invoked
- **AND** no SQL is issued

#### Scenario: Query dimension match passes validation

- **WHEN** `search_similar(query_embedding=<a list of length
  Settings.embedding_dimension>, top_k=10)` is called
- **THEN** the validation passes and the repository is invoked
- **AND** no exception is raised for the dimension check

#### Scenario: Validation order is fixed

- **WHEN** the service source is inspected
- **THEN** the first branch in `search_similar` checks `top_k > 0`
  and raises `InvalidVectorSearchTopK` otherwise
- **AND** the second branch checks `len(query_embedding) ==
  settings.embedding_dimension` and raises
  `InvalidVectorSearchDimension` otherwise
- **AND** the empty-candidate-list short-circuit appears AFTER both
  validation branches

### Requirement: Repository performs the pgvector distance query

The system SHALL provide a
`ProductoPresentacionEmbeddingSearchRepository` in
`backend/repositories/producto_presentacion_embedding_search_repository.py`
whose only SQL surface is a single read-only query that, for a given
`id_comercio`, `query_embedding`, `modelo`, `top_k`, and optional
`candidate_ids`, returns the best matching `producto_presentacion`
documents. The query SHALL:

1. Join `ProductoPresentacionEmbedding` × `ProductoPresentacion` ×
   `Producto` × `CategoriaProducto` so the commerce filter can be
   applied.
2. Filter on `CategoriaProducto.id_comercio == id_comercio` so other
   comercios are NEVER considered.
3. Filter on `ProductoPresentacionEmbedding.modelo == settings.embedding_model`
   so embeddings from other models are excluded.
4. Filter on `ProductoPresentacionEmbedding.embedding_status == 'ready'`
   so `pending`, `failed`, `stale`, and `inactive` rows are excluded.
5. Filter on `ProductoPresentacionEmbedding.activo == True`.
6. Filter on `Producto.activo == True`,
   `ProductoPresentacion.activo == True`, and
   `Producto.disponible == True` so the activity chain is end-to-end
   active and available.
7. Filter on `CategoriaProducto.activo == True` and
   `Presentacion.activo == True` so the parent chain belongs to the
   same active commerce.
8. Filter on `ProductoPresentacion.id IN (candidate_ids)` when
   `candidate_ids` is provided; when `candidate_ids` is `None` the
   filter is omitted.
9. Compute the cosine distance between the row's `vector` and
   `query_embedding` through the pgvector `<=>` operator exposed by
   the existing `VECTOR(EMBEDDING_DIMENSION)` mapping, and project the
   cosine distance as `distance` (lower = more similar) and the cosine
   similarity as `score` (`1 - distance`, higher = more similar) for
   the typed result.
10. Group by `ProductoPresentacionEmbedding.id_producto_presentacion`
    using a window function (`ROW_NUMBER() OVER (PARTITION BY
    id_producto_presentacion ORDER BY distance ASC)`) so only the
    best-scoring document per product-presentation survives.
11. Apply `top_k` AFTER the grouping so `top_k` counts unique
    product-presentations, not raw documents.
12. Order results by `score DESC` (most similar first), then by
    `id_producto_presentacion ASC` for deterministic ties.

The repository SHALL execute a single SQL statement. The repository
SHALL NOT call `session.commit()`, `session.rollback()`,
`session.close()`, or `session.begin()`. The repository SHALL NOT
import FastAPI, HTTP, the embedding client, the document builder, the
seeder, the indexer, the sync service, or any router.

#### Scenario: Single SQL statement is issued

- **WHEN** the repository is invoked with a valid `id_comercio`,
  `query_embedding`, `modelo`, `top_k`, and (optionally)
  `candidate_ids`
- **THEN** the repository executes exactly one SQL `SELECT` statement
  against `producto_presentacion_embeddings`
- **AND** no `INSERT`, `UPDATE`, or `DELETE` statement is issued

#### Scenario: Commerce isolation is enforced

- **WHEN** the repository is invoked with `id_comercio=1` against a
  table that holds rows for comercio 1 and comercio 2
- **THEN** only rows whose `CategoriaProducto.id_comercio == 1` are
  considered
- **AND** rows for comercio 2 are NOT returned

#### Scenario: Embedding status and activity chain are enforced

- **WHEN** the repository is invoked
- **THEN** rows with `embedding_status IN ('failed','stale','inactive','pending')`
  are NOT returned
- **AND** rows with `Producto.activo = False` are NOT returned
- **AND** rows with `ProductoPresentacion.activo = False` are NOT returned
- **AND** rows with `Producto.disponible = False` are NOT returned
- **AND** rows with `CategoriaProducto.activo = False` or
  `Presentacion.activo = False` are NOT returned

#### Scenario: Model isolation is enforced

- **WHEN** the repository is invoked with
  `modelo=settings.embedding_model`
- **THEN** rows whose `modelo` differs from `settings.embedding_model`
  are NOT returned
- **AND** rows for the same `id_producto_presentacion` from a
  different model are NOT mixed into the result

#### Scenario: Candidate ids restrict results

- **WHEN** the repository is invoked with `candidate_ids=[11, 99, 42]`
- **THEN** only rows whose `ProductoPresentacion.id` is in
  `{11, 99, 42}` are considered
- **AND** rows for other `id_producto_presentacion` values are NOT
  returned

#### Scenario: Best-scoring document wins per product-presentation

- **WHEN** the repository runs against a catalog that has multiple
  documents for one `id_producto_presentacion` (one `canonical`, one
  `description`, one `alias`)
- **THEN** the result contains at most one row per
  `id_producto_presentacion`
- **AND** the row carries the `source_type` of the document with the
  lowest cosine distance (highest score)

#### Scenario: top_k applies to unique product-presentations

- **WHEN** the repository is invoked with `top_k=3` against a catalog
  with ten eligible product-presentations whose documents expand to
  forty ready rows
- **THEN** the result contains at most three unique
  `id_producto_presentacion` values
- **AND** ordering is most-similar first (`score DESC`), then
  `id_producto_presentacion ASC` for deterministic ties

#### Scenario: Repository is read-only

- **WHEN** the repository module is inspected
- **THEN** the module does NOT import or call `INSERT`, `UPDATE`, or
  `DELETE` statements against `producto_presentacion_embeddings`
- **AND** the module does NOT call `session.commit()`,
  `session.rollback()`, `session.close()`, or `session.begin()`
- **AND** the module does NOT import FastAPI, HTTP, the embedding
  client, the document builder, the seeder, the indexer, the sync
  service, or any router

### Requirement: Typed result exposes only safe fields

The system SHALL expose a frozen dataclass
`ProductPresentationVectorMatch` in
`backend/services/product_presentation_vector_match.py` with exactly
three fields: `id_producto_presentacion: int`, `score: float`, and
`source_type: str`. The service SHALL return a `list[ProductPresentationVectorMatch]`
ordered from most to least similar. The result SHALL NOT expose the
raw vector, the original `source_text`, the `normalized_text`, the
`content_hash`, the `last_error`, the underlying SQLAlchemy model
instance, the `distance` value, internal exception traces, or any
persisted `Settings` field. The result SHALL inherit only from
`dataclass(frozen=True)`; it SHALL NOT be a Pydantic model, a
SQLAlchemy ORM model, or a class with side effects in
`__post_init__`.

#### Scenario: Result shape exposes only the three safe fields

- **WHEN** the result dataclass is inspected
- **THEN** it exposes only `id_producto_presentacion: int`,
  `score: float`, and `source_type: str`
- **AND** no field carries the vector, source text, normalized text,
  content hash, last error, SQLAlchemy model, or distance value

#### Scenario: Result is immutable

- **WHEN** a `ProductPresentationVectorMatch` instance is created
- **THEN** assigning to any of its fields raises `dataclasses.FrozenInstanceError`

#### Scenario: Service returns a list of typed matches

- **WHEN** the service completes a successful search
- **THEN** the return value is a `list[ProductPresentationVectorMatch]`
- **AND** the list is ordered from most similar (highest `score`) to
  least similar
- **AND** `len(returned) <= top_k`
- **AND** every `id_producto_presentacion` is unique

### Requirement: Subphase 4.6–4.8 surface is unchanged

The 4.6 indexer, seeder, document builder, persistence model,
migration, embedding client, and CLI; the 4.7 admin endpoints and
status repository; and the 4.8 sync service and its result
dataclass SHALL remain unchanged. Subphase 4.9 SHALL NOT modify the
4.6 `ProductoPresentacionEmbeddingIndexer` /
`ProductoPresentacionEmbeddingSeeder` /
`ProductoPresentacionEmbeddingAdminService` /
`ProductoPresentacionEmbeddingStatusRepository` /
`ProductoPresentacionEmbeddingIndexRepository` public surface. The
new search repository SHALL live next to them but SHALL NOT import
or subclass them. The new search service SHALL NOT depend on the
sync service, the admin service, the seeder, the indexer, the
document builder, or the embedding client.

#### Scenario: 4.6–4.8 modules are not imported by the search surface

- **WHEN** the search service and search repository modules are
  inspected
- **THEN** they do NOT import `ProductoPresentacionEmbeddingIndexer`,
  `ProductoPresentacionEmbeddingSeeder`,
  `ProductoPresentacionEmbeddingAdminService`,
  `ProductoPresentacionEmbeddingStatusRepository`,
  `ProductoPresentacionEmbeddingIndexRepository`,
  `CatalogEmbeddingSynchronizationService`, `EmbeddingSynchronizationResult`,
  `ProductEmbeddingDocumentBuilder`, `OllamaEmbeddingClient`,
  `backend.routers.admin_product_embeddings`, or any of the 4.7
  schemas

#### Scenario: 4.6–4.8 focused tests remain valid

- **WHEN** the existing 4.6, 4.7, and 4.8 focused tests are executed
  after Subphase 4.9 lands
- **THEN** they continue to pass without modification
- **AND** the 4.6 migration is the only migration for
  `producto_presentacion_embeddings`
- **AND** the `OllamaEmbeddingClient(settings, transport=None, clock=None)`
  constructor is unchanged
