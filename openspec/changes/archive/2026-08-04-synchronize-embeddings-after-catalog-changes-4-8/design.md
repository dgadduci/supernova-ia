## Context

Subphases 4.6 and 4.7 closed the embedding pipeline:

- 4.6 — `ProductoPresentacionEmbeddingIndexer` projects every applicable
  `producto_presentacion` (active and inactive), runs the pure
  `ProductEmbeddingDocumentBuilder`, batches `embed_documents` calls,
  persists through `ProductoPresentacionEmbeddingService` /
  `ProductoPresentacionEmbeddingRepository`, and reconciles `stale` /
  `inactive` / `failed` outcomes. The `ProductoPresentacionEmbeddingSeeder`
  wraps the indexer and returns a `SeedingResult` with
  `(created, updated, unchanged, stale, inactive, failed)` plus per-
  presentation `SeedingOutcome` rows. The 4.6 CLI
  (`backend/scripts/seed_product_presentation_embeddings.py`) and the
  per-batch failure handling are the contract.
- 4.7 — The local-admin `POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
  and `GET .../status` endpoints delegate to the same seeder and
  `ProductoPresentacionEmbeddingStatusRepository`. The gate is
  `Settings.enable_local_admin_endpoints`.

Both subphases preserved the strict "no commit / no rollback / no close /
no begin inside the service layer" contract and the "embedding vectors
never leak through the API" contract. No automatic catalog-change hook
was added; the 4.6 change explicitly excluded it.

The catalog mutation paths that today can invalidate embeddings are:

- `backend/services/producto_service.py` (`ProductoService.create /
  update`)
- `backend/services/categoria_producto_service.py`
  (`CategoriaProductoService.create / update`)
- `backend/services/presentacion_service.py` (`PresentacionService.create /
  update`)
- `backend/services/producto_service.py` (the `ProductoPresentacion` join
  mutations — verify location before implementing)
- `backend/services/producto_alias_service.py`
  (`ProductoAliasService.create / update / activate / deactivate / delete`)

Each service already issues the catalog write inside a caller-owned
transaction and returns to the router / CLI / orchestrator before the
outer commit. The catalog services deliberately do NOT call
`session.commit`, `session.rollback`, `session.close`, or
`session.begin`, and they do NOT invoke the synchronization service —
that contract is preserved unchanged.

## Goals / Non-Goals

**Goals:**

- Insert a thin `CatalogEmbeddingSynchronizationService` between the
  catalog commit and the caller return, delegating regeneration to the
  existing 4.6 indexer / seeder.
- Resolve the narrowest valid scope per mutation through repository
  reads only.
- Guarantee that an Ollama, embedding, or sync failure never rolls back
  the catalog change.
- Preserve every 4.6 / 4.7 invariant: no migration, no change to
  `OllamaEmbeddingClient`, no change to `ProductEmbeddingDocumentBuilder`,
  no change to the persistence model, no change to the manual reindex
  endpoint.
- Provide a typed `EmbeddingSynchronizationResult` so the caller can
  distinguish "catalog mutation succeeded and embeddings synchronized",
  "catalog mutation succeeded but sync reported failures", and "catalog
  mutation itself failed" (the last is already handled by the existing
  service boundary).

**Non-Goals:**

- No Celery / Redis / queues / workers / schedulers.
- No automatic retry policies.
- No database triggers, event bus, or event sourcing.
- No vector similarity search, no HNSW / IVFFlat indexes.
- No hybrid recognizer wiring; no fuzzy recognizer changes.
- No Subphase 4.9+ work.
- No full-commerce reindex when a narrower scope is available.
- No change to the `OllamaEmbeddingClient` constructor
  (`(settings, transport=None, clock=None)`).
- No change to the 4.7 admin reindex / status endpoints.

## Decisions

### 1. New service in `backend/services/catalog_embedding_synchronization_service.py`

The sync service lives in `backend/services/` next to the 4.6
`producto_presentacion_embedding_seeder.py` and the 4.7
`producto_presentacion_embedding_admin_service.py`. It accepts a
`Session`, a constructed `OllamaEmbeddingClient(settings)`, and a
`Settings` object through its constructor and exposes five explicit
scope methods. It does NOT import FastAPI, the admin router, the
document builder internals, the embedding client constructor body, or
the catalog mutation services. SQLAlchemy reads for scope resolution
live in repositories; the service delegates every regeneration step to
the existing 4.6 indexer / seeder.

Alternatives considered:

- Putting the sync logic inside the existing 4.7 admin service — rejected
  because the admin service is HTTP-coupled and gated by
  `Settings.enable_local_admin_endpoints`. The sync must run on every
  catalog mutation, not only when the admin flag is enabled.
- Triggering the sync through a database trigger — explicitly listed as
  a non-goal by the project outline and rejected because it would couple
  the catalog schema to Ollama availability.
- Building a new indexer variant that knows about catalog scopes —
  rejected because the 4.6 indexer already accepts the three scope
  filters; the sync is a thin orchestration layer.

### 2. New typed result in `backend/services/embedding_synchronization_result.py`

A frozen `@dataclass` with exactly `attempted`, `created`, `updated`,
`unchanged`, `stale`, `inactive`, `failed`, and `synchronization_failed`.
No vectors, no source text, no hashes, no internal exception traces.
The caller surfaces this result in the existing catalog mutation return
shape (e.g., a new field on the response schema where the project
already exposes the catalog row).

Alternatives considered:

- Returning the raw 4.6 `SeedingResult` — rejected because the catalog
  service boundary needs a stable, embedding-agnostic contract that
  cannot leak the 4.6 row shape.
- Returning a boolean "sync ok / failed" only — rejected because the
  caller benefits from the six counters when surfacing sync state to
  operators.

### 3. Repository scope-resolution reads on `ProductoPresentacionEmbeddingIndexRepository`

A single new read-only repository is preferred over scattering scope
queries across the existing catalog repositories, because the 4.6
indexer already owns the parent-chain joins and the
`CategoriaProducto.id_comercio` filter. The four new methods return
`list[int]` only (no eager loading, no ORM rows). They run bounded
`select()` queries against the existing
`producto_presentaciones × productos × categorias_productos` chain.

Alternatives considered:

- Adding the four methods to the existing `producto_repository.py`,
  `categoria_producto_service.py`, etc. — rejected because scope
  resolution requires joining the parent chain that the embedding
  indexer already owns; the read is logically part of the embedding
  read surface.
- Loading full `ProductoPresentacion` rows — rejected because the
  service only needs ids; loading rows would force eager-loading
  decisions and risk N+1.

### 4. Sync orchestration is owned by the caller, NOT by catalog services

Catalog services (`ProductoService`, `CategoriaProductoService`,
`PresentacionService`, `ProductoPresentacionService`,
`ProductoAliasService`) SHALL continue to perform only validation and
mutation. They SHALL NOT call `session.commit`, `session.rollback`,
`session.close`, `session.begin`, or any synchronization service method.
This preserves the existing strict no-transaction-in-services contract.

The router, CLI, or orchestrator owns the complete orchestration
sequence for every catalog mutation boundary:

```text
catalog mutation (validate + stage)         ← catalog service
→ session.commit() once                     ← router / CLI / orchestrator
→ scoped embedding synchronization          ← router / CLI / orchestrator
→ session.commit() once on success,         ← router / CLI / orchestrator
  session.rollback() once on unhandled
  SQLAlchemyError
```

The synchronization service is constructed with the caller's outer
`Session`, the configured `OllamaEmbeddingClient(settings)`, and the
loaded `Settings`. It NEVER calls `session.commit`, `session.rollback`,
`session.close`, or `session.begin`. On an unhandled `SQLAlchemyError`,
it returns an `EmbeddingSynchronizationResult` with
`synchronization_failed=True` and leaves transaction finalization to
the caller — the caller is responsible for rolling back ONLY the
synchronization transaction (the catalog transaction was already
committed and is unaffected). The existing `get_session` generator
remains the sole owner of `session.close()` in its `finally`; no nested
transactions are opened.

If the catalog mutation itself raises, the existing service boundary
already prevents any commit; no sync runs. If Ollama or the embedding
client raises `EmbeddingClientError`, the 4.6 seeder reports
`failed>0` with `synchronization_failed=False` and the catalog mutation
stays committed. The 4.7 manual reindex endpoint remains the operator's
recovery path.

Alternatives considered:

- Having the catalog service invoke the sync after a self-issued commit
  — rejected because it violates the "no `commit` / `rollback` /
  `close` / `begin` in the service layer" contract and because a sync
  failure inside the service would hide the failure from the caller's
  return shape. The orchestrator must own both transaction boundaries.
- Calling the sync inside the uncommitted catalog transaction —
  rejected because an Ollama failure must never roll back the catalog
  change and the project rule is "sync runs only after the catalog
  change is committed".

### 5. Embedding-relevance gating lives with the caller

Per Decision 4, the catalog service does NOT invoke the sync. The
embedding-relevance decision therefore lives with the router / CLI /
orchestrator, which knows which fields the incoming request changed.
For every catalog mutation boundary the orchestrator checks whether at
least one embedding-relevant field changed using this mapping:

- `Producto`: `nombre`, `descripcion`, `activo`, `disponible`
- `CategoriaProducto`: `descripcion`, `activo`
- `Presentacion`: `codigo`, `descripcion`, `activo`
- `ProductoPresentacion`: `activo`, `disponible`
- `ProductoAlias`: `alias`, `activo`, scope transitions
  (create / update text / activate / deactivate / delete)

`Producto.orden`, `Presentacion.orden`, etc. do NOT trigger the sync.
This keeps the sync surface minimal and the behavior predictable.

Alternatives considered:

- Reindexing on every update — rejected because it would call Ollama
  unnecessarily for unrelated fields and would risk DoS-ing the
  embedding client.
- Having the service itself signal "this update touched an embedding-
  relevant field" through a flag or callback — rejected because the
  caller already knows which fields it sent in its own request, and
  pushing the decision into the service would entangle the service with
  sync semantics.

### 6. Alias deletion captures scope BEFORE the row is removed

For `ProductoAliasService.delete`, the alias row is removed by the
catalog commit and is therefore no longer reachable by
`synchronize_alias(id_alias)` once the commit completes. To avoid
resolving a deleted alias through `id_alias`, the catalog service
captures the scope BEFORE the delete is staged:

- `id_producto` — read from the alias row pre-delete.
- `id_producto_presentacion` — read from the alias row pre-delete when
  the alias was presentation-specific.

The captured scope is exposed on the existing service return shape
(extension, not a new endpoint). After the catalog commit, the
orchestrator drives synchronization using ONLY the captured scope:

- presentation-specific alias →
  `synchronize_producto_presentacion(captured_id_producto_presentacion)`
- product-wide alias →
  `synchronize_producto(captured_id_producto)`

`synchronize_alias(id_alias)` remains the entry point for alias
create / update text / activate / deactivate (the alias row still
exists and the resolution through `id_alias` is valid), but is NOT
used for post-delete synchronization. The synchronization service
NEVER attempts to look up a deleted alias through `id_alias`; the
post-delete path bypasses `synchronize_alias` entirely and uses the
narrower `synchronize_producto` or `synchronize_producto_presentacion`
entry point with the captured scope.

Alternatives considered:

- Reading the alias scope from the database after the delete — rejected
  because the alias row is gone post-commit; resurrecting it through a
  tombstone or audit table is explicitly out of scope for 4.8.
- Calling `synchronize_alias(id_alias)` on a deleted alias and expecting
  it to fail gracefully — rejected because the project's rule is
  "never resolve a deleted alias through `id_alias`"; the caller must
  carry the scope forward.
- Synchronizing the entire product on every alias delete — rejected
  because product-wide aliases legitimately cover many presentations
  while presentation-specific aliases only cover one; the captured
  scope is the precise signal.

### 7. Test surface uses a fake `OllamaEmbeddingClient`

The 4.6 / 4.7 spec already mandates testable transport injection for
the embedding client. The new sync tests construct
`OllamaEmbeddingClient(settings, transport=fake_transport,
clock=fake_clock)` with a stub `requests`-shaped transport. The tests
do NOT require a real Ollama server. The 4.6 / 4.7 focused tests are
preserved unchanged.

Alternatives considered:

- Spinning up a test Ollama container — rejected by the project
  outline and unnecessary because the 4.6 transport injection is
  already the project's testing convention.

## Risks / Trade-offs

- **Sync latency on the catalog path** — Calling the embedding client
  inline after a catalog commit adds Ollama round-trips to the HTTP
  response. Mitigation: only call sync when an embedding-relevant
  field changed; the projected batch is bounded by
  `Settings.embedding_batch_size`; the existing 4.6 batching keeps the
  per-batch cost bounded. The catalog row is already committed by the
  time the sync runs, so HTTP latency is decoupled from catalog
  durability.

- **Ollama unavailability degrades the embedding state silently** —
  When Ollama is down, the sync reports `failed>0` and
  `synchronization_failed=False` (recoverable failure) and the operator
  is expected to use the 4.7 manual reindex endpoint. Mitigation: the
  4.7 endpoint remains reachable, the 4.6 status repository exposes the
  per-status counts, and the sync result is exposed on the catalog
  response so a future observability surface can surface it.

- **Sync race with concurrent catalog mutations** — Two concurrent
  mutations on the same presentation may issue two overlapping sync
  calls. Mitigation: each sync call delegates to the same 4.6 indexer
  / seeder; the underlying hash comparison and state machine are
  idempotent. The worst case is redundant Ollama calls, not data
  corruption. A future subphase can introduce a per-presentation lock
  if profiling demands it.

- **New service surface increases the import graph** — The sync service
  imports the 4.6 indexer, the 4.6 seeder, the embedding client, the
  status repository, and four new repository methods. Mitigation: the
  service does NOT import FastAPI, the admin router, the document
  builder, or the catalog mutation services, keeping the dependency
  surface tight.

- **Field-level gating depends on every catalog service correctly
  identifying the embedding-relevant fields** — A future field
  addition (e.g., a new `Producto.alias_visible` column) could become
  embedding-relevant without the sync noticing. Mitigation: the
  field-set is documented in `specs/catalog-embedding-synchronization/spec.md`
  and any new embedding-relevant field requires an OpenSpec change
  to the sync requirements. Tests assert the current field set is
  respected.

## Migration Plan

This subphase introduces no migration. The 4.6 schema
(`producto_presentacion_embeddings`) and the 4.3 migration
(`CREATE EXTENSION IF NOT EXISTS vector` + table) remain the only
persistence surface. The new repository methods, the new service, and
the new typed result are additive.

Rollback:

- Disable the sync by removing the catalog-orchestration call site in
  the router / CLI / orchestrator (one block per affected boundary).
  The catalog mutations continue to commit through the existing
  caller-owned path; the 4.7 manual reindex endpoint remains reachable.
- Delete the new service file, the new result file, the new repository
  methods, and the new tests. No database rollback is required.

## Open Questions

- The exact location of the `ProductoPresentacion` mutation path
  (likely `ProductoService.create_presentacion` / `update_presentacion`
  or a separate `ProductoPresentacionService`) must be confirmed during
  implementation. The spec references both `ProductoService` and a
  possible `ProductoPresentacionService`; the implementer will choose
  the file that already owns the mutation and add the sync call there.
- The 4.6 `ProductoPresentacionEmbeddingIndexer` exposes
  `index_presentations(...)` with the three scope filters. Whether to
  invoke the indexer once per affected `id_producto_presentacion` (to
  keep the per-call scope minimal) or once per broader filter (to
  avoid per-call projection overhead) is an implementation detail; the
  chosen approach MUST keep the `SeedingResult` counters sumable across
  calls and MUST match the per-presentation outcomes the manual reindex
  would have produced.
