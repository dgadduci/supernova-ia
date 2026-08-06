## Context

Subphase 4.6 shipped the `producto_presentacion_embeddings` table with
the per-document model, persistence boundary, indexer, seeder, status
repository, and CLI. Subphase 4.7 added a local-admin 4.7 surface
(`ProductoPresentacionEmbeddingAdminService`, the
`POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
endpoint, the `GET .../status` endpoint) gated by
`Settings.enable_local_admin_endpoints`. Subphase 4.8 layered
`CatalogEmbeddingSynchronizationService` plus
`EmbeddingSynchronizationResult` on top so catalog mutations
reindex the narrowest valid embedding scope.

The current state is a write-only pipeline: every approved catalog
mutation generates and stores embeddings, but nothing reads them
back. The recognizer still relies on the legacy fuzzy match for
catalog candidates, and the customer-message flow cannot benefit from
the embedding work. Subphase 4.9 is the explicit read path that
Subphase 4.5's "later subphases can focus on ... vector search"
preview called for.

The implementation must respect the established 4.6–4.8 architecture:
SQLAlchemy + pgvector stays in repositories, services own validation
and result mapping, and neither layer calls `commit` / `rollback` /
`close` / `begin`. The new search surface is a sibling of the 4.7
status repository and the 4.8 sync service — it does not consume
either of them.

## Goals / Non-Goals

**Goals:**

- Add a typed `ProductPresentationVectorSearchService` that exposes
  `search_similar(*, id_comercio, query_embedding, top_k,
  candidate_producto_presentacion_ids=None)` returning a
  `list[ProductPresentationVectorMatch]` ordered from most to least
  similar.
- Add a `ProductoPresentacionEmbeddingSearchRepository` whose only SQL
  surface is a single pgvector cosine-distance query that joins the
  full parent chain and enforces commerce isolation, model isolation,
  embedding-status filtering, and the activity chain.
- Add a frozen `ProductPresentationVectorMatch` dataclass with exactly
  `id_producto_presentacion`, `score`, and `source_type`.
- Validate `top_k > 0` and `query_embedding` length against
  `Settings.embedding_dimension` before any SQL is issued, in this
  exact order: top_k first, then dimension. The empty-candidate-list
  short-circuit returns `[]` AFTER both validations pass, so
  `top_k <= 0` and a wrong-dimension `query_embedding` still raise
  even when the candidate list is empty.
- Return `[]` immediately when `candidate_producto_presentacion_ids == []`
  without issuing any SQL.
- Collapse to one match per `id_producto_presentacion` (the best
  scoring document wins) and apply `top_k` after grouping.
- Focus on the typed result contract: no vector, no `source_text`,
  no `normalized_text`, no `content_hash`, no `last_error`, no
  SQLAlchemy model, no `distance` value, no internal exception trace
  leak.
- Add two domain exceptions (`InvalidVectorSearchDimension`,
  `InvalidVectorSearchTopK`) and a focused test suite covering the 15
  scenarios in the project playbook, the new validation-order tests
  (invalid top_k wins over empty candidate list, invalid dimension
  wins over empty candidate list, invalid top_k wins over invalid
  dimension), and the 4.6–4.8 regression guard.

**Non-Goals:**

- Embedding generation from query text, calls to
  `OllamaEmbeddingClient`, fuzzy / vector score fusion, hybrid
  recognizer routing, intent execution, customer-facing endpoints,
  background jobs, catalog synchronization changes, or mutations of
  `producto_presentacion_embeddings`.
- HNSW / IVFFlat index migration. Exact search is acceptable for the
  current development-scale catalog.
- New HTTP endpoints, CLI surface, or routers.
- Subphase 4.10 work and any unrelated smoke-test debt.

## Decisions

### Decision 1 — pgvector operator choice: cosine distance (`<=>`)

The 4.6 model already declares `vector: Mapped[list[float] | None] = mapped_column(
VECTOR(EMBEDDING_DIMENSION), nullable=True)`. pgvector exposes the
`<=>` cosine distance operator; L2 (`<->`) and inner product (`<#>`)
are also available, but the existing pipeline uses the default
unconfigured distance which falls back to L2. Cosine is the closest
match for normalized semantic embeddings and is what the project
playbook calls out as "the distance operator supported by the existing
pgvector mapping". The result is exposed as `score = 1 - distance`
(higher = more similar) so the typed contract stays intuitive.

Alternative considered: L2 distance. Rejected because it is sensitive
to vector magnitude and the embedding pipeline does not normalize
output vectors through cosine L2.

Alternative considered: inner product (`<#>`). Rejected because the
embedding client does not guarantee unit-length vectors and the
playbook explicitly calls for cosine.

### Decision 2 — Group-by via `ROW_NUMBER() OVER (PARTITION BY ...)` subquery

The query must return the best-scoring document per
`id_producto_presentacion` and apply `top_k` after grouping. The
cleanest SQL is a `ROW_NUMBER()` window partitioned by
`id_producto_presentacion`, ordered by `distance ASC`, then filtered
to `row_number = 1` inside a subquery, and finally wrapped by a
`LIMIT top_k` outer query. This is a single SQL statement and uses
only pgvector-supported window functions.

Alternative considered: `DISTINCT ON` in PostgreSQL. Rejected because
SQLAlchemy 2.x's `select()` abstraction is friendlier to a
`ROW_NUMBER()` subquery and the existing tests already use the ORM
`select()` style.

Alternative considered: doing the grouping in Python after fetching
all rows. Rejected because the playbook requires `top_k` to apply to
unique product-presentations, and pulling every ready row to filter in
Python defeats the purpose of `top_k`.

### Decision 3 — Service is the only collaborator on the repository

The service constructs the repository internally from the caller's
`Session`. No factory is introduced; the service is a plain class
with `__init__(self, session: Session, settings: Settings)` and a
single `search_similar(...)` method. This mirrors the existing 4.6
`ProductoPresentacionEmbeddingIndexer` and 4.8
`CatalogEmbeddingSynchronizationService` constructor patterns and
keeps tests trivial (`service = ProductPresentationVectorSearchService(
session, settings)`).

Alternative considered: passing the repository as a constructor
argument. Rejected because there is exactly one implementation and
the playbook keeps the injection surface minimal ("the service owns
validation and result mapping").

### Decision 4 — Validation happens before the repository, never inside it, in a fixed order

`top_k <= 0` and a wrong-dimension `query_embedding` both raise a
`ValueError` subclass in the service, in this exact order: top_k
first, then dimension. The empty-candidate-list short-circuit
(returning `[]`) appears AFTER both validations, so a malformed query
never reaches the database and the empty-candidate-list path never
silently swallows invalid input. The repository trusts the service
and is allowed to assume the inputs are valid. Validation errors
therefore never reach the database, and the test suite can assert
that the repository is not invoked by spying on its method.

Alternative considered: validating inside the repository. Rejected
because the playbook explicitly says "rejected before SQL execution"
and "repository performs the pgvector distance query" — the
repository owns SQL, not validation.

Alternative considered: short-circuiting empty candidates before the
top_k / dimension validations. Rejected because the empty-candidate
path is a "no matches" outcome, not a "skip validation" outcome; the
playbook requires that invalid input always raises, regardless of
the candidate list.

### Decision 5 — No HNSW / IVFFlat migration in this subphase

The current development-scale catalog is small enough that exact
search is acceptable. The existing
`(id_producto_presentacion, modelo)` indexes already cover the join
and the WHERE clause, and the
`(id_producto, id_categoria_producto, nombre)` /
`(id_producto_presentacion, id_producto, id_categoria_producto)` /
`embedding_status` activity filters narrow the row set before the
pgvector distance evaluation.

A future subphase may add HNSW when the catalog grows enough to make
the query plan meaningful. The playbook explicitly says "Do not add
HNSW or IVFFlat merely for theoretical optimization. Add a migration
only if an index is already required by the approved roadmap".

Alternative considered: ship an HNSW index now. Rejected because the
project playbook calls out premature migration complexity as a real
risk.

### Decision 6 — Typed result is a frozen dataclass, not a Pydantic model

The result has no JSON serialization path in this subphase — the
recognizer and the customer-message flow are future work. A frozen
`dataclass` keeps the contract minimal, makes immutability obvious,
and avoids the ceremony of a Pydantic model with no current consumer.

Alternative considered: a Pydantic schema. Rejected because the
result is internal to the new service layer for now, and Pydantic
models introduce error messages that do not yet have a router
mapping.

### Decision 7 — `score` is the only distance-like field exposed

The raw cosine distance is kept inside the repository (used for the
ordering) but never returned to the caller. The service maps
`(distance, source_type, id_producto_presentacion)` to
`ProductPresentationVectorMatch(score=1 - distance, source_type=...,
id_producto_presentacion=...)`. This matches the project playbook
("not expose vectors, source text, hashes, database models, or
internal exceptions") and keeps the result ordered from most to
least similar without making the operator reason about smaller-is-
better.

Alternative considered: returning both `score` and `distance`. Rejected
because the playbook lists only `score or distance` (one, not both).

## Risks / Trade-offs

- [Risk] Exact search scans every ready row in the
  `producto_presentacion_embeddings` table once the catalog grows.
  → [Mitigation] The current catalog is small enough that exact
  search is acceptable; the active chain filters and the
  `(id_producto_presentacion, modelo)` index already narrow the row
  set. A future subphase can add HNSW without changing the public
  surface (`search_similar`).
- [Risk] Window function + LIMIT adds a small per-query cost versus
  a flat LIMIT. → [Mitigation] The grouping is required by the
  playbook ("apply `top_k` after grouping") and the cost is bounded
  by the per-commerce ready-row count, which is small for the
  current catalog.
- [Risk] The new search surface becomes a tempting dependency for
  the recognizer before the catalog-aware hybrid routing lands.
  → [Mitigation] The non-goals explicitly forbid recognizer
  integration in this subphase; the spec includes a "Subphase
  4.6–4.8 surface is unchanged" requirement plus a 4.6–4.8
  regression test so future wiring stays explicit.
- [Risk] `Producto.disponible` is the only `disponible` field in the
  parent chain; `ProductoPresentacion` does not expose one. The
  spec interprets "the product-presentation is active and
  available" as `ProductoPresentacion.activo = True AND
  Producto.disponible = True`. → [Mitigation] The repository SQL
  filters on the explicit field set documented in the
  `Repository performs the pgvector distance query` requirement
  and the spec scenario lists the seven predicates directly so the
  contract is auditable.
- [Risk] A non-unit-norm `query_embedding` produces a non-zero
  cosine distance for a vector that is semantically identical to a
  stored vector. → [Mitigation] The project playbook does not
  require query normalization in this subphase; the operator (or
  future subphase) is responsible for handing the service a
  query vector that matches the corpus shape. The spec stays
  silent on this normalization so the contract is minimal.
