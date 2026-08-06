## 1. Inspect real 4.6 / 4.7 surface before editing

- [x] 1.1 Read `backend/services/producto_presentacion_embedding_indexer.py` and confirm `index_presentations(...)` accepts the three scope filters
- [x] 1.2 Read `backend/services/producto_presentacion_embedding_seeder.py` and confirm the `SeedingResult` / `SeedingOutcome` shape
- [x] 1.3 Read `backend/repositories/producto_presentacion_embedding_index_repository.py` and the 4.7 status repository for the existing parent-chain joins
- [x] 1.4 Read `backend/services/producto_presentacion_embedding_admin_service.py` to confirm the no-commit / no-rollback / no-close / no-begin contract
- [x] 1.5 Read the four catalog services (`producto_service.py`, `categoria_producto_service.py`, `presentacion_service.py`, `producto_alias_service.py`) and locate the actual `ProductoPresentacion` mutation method
- [x] 1.6 Read the existing catalog routers to confirm the outer caller owns both `commit()` and the sync transaction boundary
- [x] 1.7 Inspect `backend/embeddings/` to confirm the `OllamaEmbeddingClient(settings, transport=None, clock=None)` constructor and the test-transport injection pattern

## 2. Add the typed result

- [x] 2.1 Create `backend/services/embedding_synchronization_result.py` with the frozen `EmbeddingSynchronizationResult` dataclass
- [x] 2.2 Expose only the documented fields: `attempted`, `created`, `updated`, `unchanged`, `stale`, `inactive`, `failed`, `synchronization_failed`
- [x] 2.3 Add a small factory function `empty_result()` returning `attempted=False, ...=0, synchronization_failed=False` for the empty-scope case
- [x] 2.4 Verify the module imports only stdlib + the existing typed result patterns (no FastAPI, no SQLAlchemy)

## 3. Add scope-resolution repository methods

- [x] 3.1 Add `list_producto_presentacion_ids_by_producto(id_producto) -> list[int]` (read-only, bounded `select()`)
- [x] 3.2 Add `list_producto_presentacion_ids_by_categoria(id_categoria) -> list[int]` (joins `producto` × `categoria_producto`)
- [x] 3.3 Add `list_producto_presentacion_ids_by_presentacion(id_presentacion) -> list[int]`
- [x] 3.4 Add `list_producto_presentacion_ids_by_alias(id_alias) -> list[int]` (returns the single presentation id or all product presentation ids)
- [x] 3.5 Confirm the new methods do NOT call `commit`, `rollback`, `close`, or `begin`
- [x] 3.6 Confirm the new methods do NOT issue `INSERT`, `UPDATE`, or `DELETE`

## 4. Add the synchronization service

- [x] 4.1 Create `backend/services/catalog_embedding_synchronization_service.py`
- [x] 4.2 Constructor accepts `(session: Session, embedding_client: OllamaEmbeddingClient, settings: Settings)`
- [x] 4.3 Implement `synchronize_producto(id_producto) -> EmbeddingSynchronizationResult` that resolves ids through the new repository method and calls the indexer / seeder per id
- [x] 4.4 Implement `synchronize_producto_presentacion(id_producto_presentacion) -> EmbeddingSynchronizationResult` that delegates directly with the scope filter
- [x] 4.5 Implement `synchronize_categoria(id_categoria) -> EmbeddingSynchronizationResult` that resolves ids and calls the indexer / seeder per id
- [x] 4.6 Implement `synchronize_presentacion(id_presentacion) -> EmbeddingSynchronizationResult` that resolves ids and calls the indexer / seeder per id
- [x] 4.7 Implement `synchronize_alias(id_alias) -> EmbeddingSynchronizationResult` that resolves the alias and delegates to the narrower entry point. This entry point is for alias create / update text / activate / deactivate only — NOT for post-delete synchronization (post-delete uses the captured scope with `synchronize_producto` or `synchronize_producto_presentacion`)
- [x] 4.8 Aggregate the per-call `SeedingResult` counters into the `EmbeddingSynchronizationResult`; do NOT reclassify outcomes
- [x] 4.9 Wrap the sync in a try / except that distinguishes recoverable failure (`failed>0` from the 4.6 seeder) from unhandled persistence errors (`SQLAlchemyError` → `synchronization_failed=True`)
- [x] 4.10 Verify the module does NOT import FastAPI, the admin router, the document builder, or the catalog mutation services
- [x] 4.11 Verify the module does NOT call `session.commit`, `session.rollback`, `session.close`, or `session.begin`

## 5. Move orchestration to the caller; capture alias scope before delete

- [x] 5.1 Verify the four catalog services (`ProductoService`, `CategoriaProductoService`, `PresentacionService`, `ProductoPresentacionService`, `ProductoAliasService`) do NOT call `session.commit`, `session.rollback`, `session.close`, or `session.begin`, and do NOT invoke the synchronization service
- [x] 5.2 Extend the existing catalog service return shapes so each path exposes the narrowest valid embedding scope (`id_producto`, `id_producto_presentacion`, `id_categoria`, `id_presentacion`, or `(id_producto, id_producto_presentacion)` for aliases) without changing the existing fields
- [x] 5.3 In `ProductoAliasService.delete`, capture `id_producto` and (when present) `id_producto_presentacion` from the alias row BEFORE the deletion is staged, and expose that captured scope on the return value
- [x] 5.4 Update the router / CLI / orchestrator for every catalog mutation boundary to run the orchestration sequence:
  ```
  catalog service (validate + stage)
  → session.commit() once
  → scoped embedding synchronization
  → session.commit() once on success / session.rollback() once on unhandled persistence error
  ```
- [x] 5.5 For `ProductoAliasService.delete`, use the captured `(id_producto, id_producto_presentacion)` scope to invoke `synchronize_producto_presentacion(captured_id_producto_presentacion)` for presentation-specific aliases, or `synchronize_producto(captured_id_producto)` for product-wide aliases. NEVER resolve a deleted alias through `id_alias`
- [x] 5.6 For other catalog mutations, drive sync through the existing service entry points (`synchronize_producto`, `synchronize_categoria`, `synchronize_presentacion`, `synchronize_producto_presentacion`, `synchronize_alias`) using the captured scope
- [x] 5.7 Verify the router / CLI / orchestrator returns a safe `EmbeddingSynchronizationResult` (with `synchronization_failed=True` and `attempted=False`, every counter `0`) when the synchronization transaction must be rolled back, and that the catalog row remains committed

## 6. Focused tests for the sync service

- [x] 6.1 Add `backend/tests/test_catalog_embedding_synchronization_service.py` with a fake `OllamaEmbeddingClient` (stub transport)
- [x] 6.2 Test: product name change reindexes all its presentations and aggregates counters
- [x] 6.3 Test: unrelated product field change (e.g., `orden`) does NOT invoke the sync (covered by empty-scope short-circuit when only `orden` changes do not introduce presentations)
- [x] 6.4 Test: category name change reindexes only that category's products' presentations
- [x] 6.5 Test: presentation code change reindexes only the linked product-presentations
- [x] 6.6 Test: product-presentation flag change reindexes only itself
- [x] 6.7 Test: product-wide alias change reindexes every presentation of the product
- [x] 6.8 Test: presentation-specific alias change reindexes only its presentation
- [x] 6.9 Test: alias deletion / deactivation produces `stale` reconciliation through the existing 4.6 path (covered by post-delete sync using captured scope)
- [x] 6.10 Test: inactive catalog change produces `inactive` rows without unnecessary Ollama calls
- [x] 6.11 Test: successful catalog mutation remains committed when Ollama raises `EmbeddingClientError` (the result carries `failed>0`, `synchronization_failed=False`)
- [x] 6.12 Test: unhandled `SQLAlchemyError` produces `synchronization_failed=True` and does NOT roll back the catalog change
- [x] 6.13 Test: commerce isolation — sync for `comercio_id=1` does not read embeddings for `comercio_id=2`
- [x] 6.14 Test: empty scope short-circuits without Ollama
- [x] 6.15 Test: alias delete captures `id_producto` and `id_producto_presentacion` from the alias row BEFORE deletion; the orchestrator's sync receives the captured scope (NOT `id_alias`); no id_alias resolution is attempted after the alias commit
- [x] 6.16 Test: caller-owned orchestration — when synchronization raises an unhandled `SQLAlchemyError`, the caller rolls back only the synchronization transaction, the catalog row stays committed, and the returned result has `synchronization_failed=True`

## 7. Regression checks

- [x] 7.1 Re-run the existing 4.6 CLI focused tests — 7 pass
- [x] 7.2 Re-run the existing 4.7 admin-endpoint focused tests — 13 pass + 7 module-boundary pass
- [x] 7.3 Re-run the existing catalog service focused tests (product, category, presentation, alias) — 31 pass
- [x] 7.4 Run `python -m compileall backend` and confirm exit 0 — confirmed
- [x] 7.5 Run `openspec validate --strict` and confirm valid — `openspec validate synchronize-embeddings-after-catalog-changes-4-8 --strict` reports valid
- [x] 7.6 Run the existing `api_smoke.py` smoke suite — 7/7 catalog HTTP tests pass (4 pre-existing failures in unrelated pending-context orchestration tests, confirmed pre-existing by stash + re-run)

## 8. Documentation & sync

- [x] 8.1 Do NOT run `/opsx:sync` (synchronization is manual and requires a separate explicit user command)
- [x] 8.2 Do NOT run `/opsx:archive` (archival is manual and requires a separate explicit user command)
- [x] 8.3 Leave the change active under `openspec/changes/synchronize-embeddings-after-catalog-changes-4-8/`
- [x] 8.4 After implementation, stop and report completed tasks, tests executed, and unresolved issues
