## Why

Subphases 4.6 and 4.7 delivered the per-document product-presentation embedding
indexer, seeder, persistence layer, status repository, and the gated local-admin
reindex/status endpoints. Today embeddings are only refreshed when an operator
manually invokes the CLI (`backend/scripts/seed_product_presentation_embeddings.py`)
or the `POST /admin/comercios/{comercio_id}/product-embeddings/reindex` endpoint.
Whenever the catalog changes (product name / description / active / available,
category text / active, presentation code / description / active, product-
presentation active / available, alias create / update / activate / deactivate /
delete), the persisted vectors continue to represent obsolete catalog text.

Subphase 4.8 closes that gap by connecting the existing catalog mutation paths
to the existing 4.6 indexer/seeder through a thin synchronization service. The
service identifies the narrowest valid embedding scope per mutation, delegates
regeneration to the existing pipeline, and never blocks or rolls back a
catalog change because Ollama is unavailable. Synchronization orchestration
(when to commit the catalog, when to invoke the sync service, when to commit
or roll back the synchronization transaction) is owned by the router, CLI,
or orchestrator — never by a catalog service.

## What Changes

- Add `CatalogEmbeddingSynchronizationService` exposing explicit scope methods
  (`synchronize_producto`, `synchronize_producto_presentacion`,
  `synchronize_categoria`, `synchronize_presentacion`, `synchronize_alias`).
  Each method delegates to the existing 4.6 `ProductoPresentacionEmbeddingIndexer`
  / `ProductoPresentacionEmbeddingSeeder` using the existing scoped filters; no
  document building, batching, hash comparison, state machine, or client
  construction is duplicated.
- Add a typed result (`EmbeddingSynchronizationResult`) carrying
  `attempted`, `created`, `updated`, `unchanged`, `stale`, `inactive`,
  `failed`, and `synchronization_failed` so callers can distinguish
  "catalog mutation succeeded and embeddings synchronized",
  "catalog mutation succeeded but sync reported failures", and
  "catalog mutation itself failed and was rolled back".
- Add minimal repository methods that resolve the narrowest affected scope
  (presentations of a product, presentations of a category, presentations
  referencing a presentation, presentation for an alias) using SQLAlchemy
  reads only.
- Integrate the synchronization service into the existing catalog mutation
  boundaries through orchestration in the router, CLI, or orchestrator — NOT
  through the catalog services themselves. The ownership sequence is:

  ```text
  catalog mutation (validate + stage)         ← catalog service
  → session.commit()                          ← router / CLI / orchestrator
  → scoped embedding synchronization          ← router / CLI / orchestrator
  → session.commit()                          ← router / CLI / orchestrator
  ```

  If synchronization raises an unhandled persistence error, only the
  synchronization transaction is rolled back; the catalog mutation stays
  committed and the caller returns a safe
  `EmbeddingSynchronizationResult` with `synchronization_failed=True`.

  Catalog services (`ProductoService`, `CategoriaProductoService`,
  `PresentacionService`, `ProductoPresentacionService`,
  `ProductoAliasService`) SHALL continue to perform only validation and
  mutation. They SHALL NOT call `session.commit`, `session.rollback`,
  `session.close`, or `session.begin`, and they SHALL NOT invoke the
  synchronization service. They SHALL expose the narrowest valid embedding
  scope on the existing return shape so the caller can drive sync.

  For `ProductoAliasService.delete`, the service SHALL capture
  `id_producto` and (when present) `id_producto_presentacion` from the
  alias row BEFORE the deletion is staged, and SHALL expose that captured
  scope on its return value. The caller uses the captured scope to drive
  synchronization after the catalog commit; the synchronization service
  NEVER attempts to resolve a deleted alias through `id_alias`.
- Preserve the 4.6 / 4.7 contracts unchanged: no migration, no change to
  `OllamaEmbeddingClient`, no change to `ProductEmbeddingDocumentBuilder`,
  no change to the embedding persistence model, no change to the manual
  reindex endpoint behavior.

## Capabilities

### New Capabilities

- `catalog-embedding-synchronization`: A new service and typed result that
  determine the narrowest valid embedding scope after a catalog mutation
  and delegate immediate regeneration to the existing 4.6 indexer/seeder
  pipeline, preserving the catalog mutation on embedding failure.

### Modified Capabilities

- `product-presentation-embedding-indexing`: Allow the existing 4.6
  indexer/seeder to be invoked after catalog mutations using its current
  scoped filters and failure semantics. No change to document building,
  hash comparison, batching, state transitions, or client construction.

## Impact

- New code:
  - `backend/services/catalog_embedding_synchronization_service.py`
  - `backend/services/embedding_synchronization_result.py` (typed result)
  - Focused tests under `backend/tests/`
- Existing catalog services touched (return shape extended to expose the
  narrowest valid embedding scope; no `commit` / `rollback` / `close` / `begin`
  and no sync invocation added):
  `ProductoService`, `CategoriaProductoService`, `PresentacionService`,
  `ProductoPresentacionService`, `ProductoAliasService`. These services
  still do not call `commit`, `rollback`, `close`, or `begin`, and they do
  NOT invoke the synchronization service.
- Existing router / CLI / orchestrator caller extended (orchestration
  sequence — `catalog mutation → commit catalog → sync → commit / rollback
  sync`) for every catalog mutation path: `ProductoService.update`,
  `CategoriaProductoService.update`, `PresentacionService.update`, the
  `ProductoPresentacion` mutation path, and `ProductoAliasService.create /
  update / activate / deactivate / delete`. The router / CLI / orchestrator
  is the sole owner of BOTH transaction lifecycles (catalog commit and
  synchronization commit / rollback).
- For `ProductoAliasService.delete`, the router / CLI / orchestrator uses
  the captured `(id_producto, id_producto_presentacion)` scope from the
  service return value to invoke
  `synchronize_producto_presentacion(captured_id_producto_presentacion)`
  for presentation-specific aliases or
  `synchronize_producto(captured_id_producto)` for product-wide aliases.
  No `id_alias` is ever resolved against a deleted alias row during
  synchronization.
- Affected repos: minimal `list_presentaciones_by_producto`,
  `list_presentaciones_by_categoria`, `list_presentaciones_by_presentacion`,
  `list_presentaciones_by_alias` reads are added to the existing
  `ProductoPresentacionEmbeddingIndexRepository` (or a new read-only
  projection) — implementation will pick whichever path matches the 4.6
  conventions after inspection.
- No new migration, no new tables, no changes to existing endpoints.
- Subphase 4.7's `POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
  and `GET .../status` remain available for manual retry when sync reports
  failures.
