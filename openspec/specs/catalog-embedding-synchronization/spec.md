# Capability: catalog-embedding-synchronization

## Purpose

TBD

## Requirements

### Requirement: CatalogEmbeddingSynchronizationService exposes narrowest-scope entry points

The system SHALL provide a `CatalogEmbeddingSynchronizationService` in
`backend/services/catalog_embedding_synchronization_service.py` that exposes
explicit scope entry points — `synchronize_producto(id_producto: int) -> EmbeddingSynchronizationResult`,
`synchronize_producto_presentacion(id_producto_presentacion: int) -> EmbeddingSynchronizationResult`,
`synchronize_categoria(id_categoria: int) -> EmbeddingSynchronizationResult`,
`synchronize_presentacion(id_presentacion: int) -> EmbeddingSynchronizationResult`,
and `synchronize_alias(id_alias: int) -> EmbeddingSynchronizationResult`. The
service SHALL accept an `OllamaEmbeddingClient` (constructed from
`load_settings()`, the same way 4.6 builds it) and the project's loaded
`Settings` through its constructor. The service SHALL NOT call
`session.commit()`, `session.rollback()`, `session.close()`, or
`session.begin()` on any session it receives. The service SHALL NOT import
FastAPI, HTTP, the embedding client constructor body, the document builder
internals, or any catalog mutation logic; it SHALL depend on the existing
4.6 `ProductoPresentacionEmbeddingIndexer` / `ProductoPresentacionEmbeddingSeeder`
and the existing 4.7 status repository through their public service surface
ONLY. SQLAlchemy reads for scope resolution SHALL live in repositories; the
service SHALL NOT issue `select()` calls directly.

#### Scenario: Each scope method delegates to the 4.6 indexer/seeder

- **WHEN** the service is constructed with a real `Session`, a real
  `OllamaEmbeddingClient(settings)` instance, and a real `Settings` object
- **THEN** `synchronize_producto(7)` calls the indexer with
  `id_producto=7` and no `id_comercio` / `id_producto_presentacion` filter
- **AND** `synchronize_producto_presentacion(31)` calls the indexer with
  `id_producto_presentacion=31`
- **AND** `synchronize_categoria(5)` resolves the affected
  `id_producto_presentacion` set through a repository and calls the indexer
  per affected presentation
- **AND** `synchronize_presentacion(12)` resolves the affected
  `producto_presentaciones` through a repository and calls the indexer per
  affected presentation
- **AND** `synchronize_alias(42)` resolves the alias's
  `id_producto` / `id_producto_presentacion` and delegates to the matching
  narrower entry point

#### Scenario: Service does not own commit / rollback / close / begin

- **WHEN** the service module is inspected
- **THEN** the module does NOT import or call `session.commit()`,
  `session.rollback()`, `session.close()`, or `session.begin()` anywhere
- **AND** the service does NOT call `OllamaEmbeddingClient.embed_documents`
  directly; the existing indexer owns the call

#### Scenario: Service does not import HTTP or router modules

- **WHEN** the service module is inspected
- **THEN** it does NOT import FastAPI, `APIRouter`, `HTTPException`, or
  any router module
- **AND** it does NOT import the document builder, the embedding client
  constructor body, or the catalog mutation services' internals

### Requirement: EmbeddingSynchronizationResult distinguishes catalog vs sync outcomes

The system SHALL expose a frozen dataclass `EmbeddingSynchronizationResult`
in `backend/services/embedding_synchronization_result.py` carrying exactly
the fields `attempted: bool`, `created: int`, `updated: int`,
`unchanged: int`, `stale: int`, `inactive: int`, `failed: int`, and
`synchronization_failed: bool`. `attempted=False` SHALL be returned only
when the caller's scope was empty (no affected presentation) or when an
unexpected persistence / synchronization error prevented any outcome from
being produced. `synchronization_failed=True` SHALL be returned when the
4.6 seeder produced no recoverable result and the synchronization
transaction had to roll back. The result SHALL NOT include embedding
vectors, source text, normalized text, content hashes, customer messages,
internal exception traces, or the persisted `Settings`.

#### Scenario: Successful empty scope reports attempted=False without failure

- **WHEN** the service is called for a `id_producto` that owns no active
  `producto_presentaciones`
- **THEN** the returned result has `attempted=False`,
  `synchronization_failed=False`, every counter `0`, and no Ollama call
  was issued

#### Scenario: Successful real run reports counters

- **WHEN** the service is called for a `id_producto_presentacion` and the
  4.6 seeder returns `created=2, updated=1, unchanged=4, stale=0, inactive=0, failed=0`
- **THEN** the returned result carries those counts, `attempted=True`, and
  `synchronization_failed=False`

#### Scenario: Recoverable failures preserve the catalog change

- **WHEN** the service is called and the 4.6 seeder returns
  `failed=2` because the embedding client raised `EmbeddingClientError`
  for one batch
- **THEN** the returned result carries `failed=2`, `attempted=True`,
  `synchronization_failed=False`
- **AND** the previously committed catalog change is NOT rolled back

#### Scenario: Unhandled persistence error rolls back only the sync

- **WHEN** the service is called and an unhandled `SQLAlchemyError` is
  raised before any recoverable result can be produced
- **THEN** the returned result has `synchronization_failed=True`,
  `attempted=False`, every counter `0`
- **AND** the synchronization transaction is rolled back by the caller
- **AND** the previously committed catalog change is NOT rolled back

#### Scenario: Result does not leak vectors or source text

- **WHEN** the result dataclass is inspected
- **THEN** it exposes no field that mirrors the `vector` column, the
  `source_text` column, the `normalized_text` column, the `content_hash`
  column, the `last_error` column, or any persisted embedding metadata

### Requirement: Sync orchestration is owned by the caller; catalog services do not invoke sync

The integration between the catalog mutation paths and the
`CatalogEmbeddingSynchronizationService` SHALL preserve the existing
service-layer rule: catalog services SHALL call
`session.commit()`, `session.rollback()`, `session.close()`, or
`session.begin()` exactly as they did before this change, and SHALL
NOT invoke the synchronization service. Catalog services SHALL
continue to perform only validation and mutation; the narrowest valid
embedding scope SHALL be exposed on the existing service return shape
so the caller can drive synchronization.

The router, CLI, or orchestrator SHALL own the complete orchestration
sequence for every catalog mutation boundary:

```text
catalog mutation (validate + stage)         ← catalog service
→ session.commit() once                     ← router / CLI / orchestrator
→ scoped embedding synchronization          ← router / CLI / orchestrator
→ session.commit() once on success,         ← router / CLI / orchestrator
  session.rollback() once on unhandled
  SQLAlchemyError
```

The synchronization service SHALL receive the caller's outer `Session`
and SHALL NOT call `session.commit()`, `session.rollback()`,
`session.close()`, or `session.begin()`. On an unhandled
`SQLAlchemyError`, the service SHALL return an
`EmbeddingSynchronizationResult` with `synchronization_failed=True`
and `attempted=False` (every counter `0`); the caller SHALL then
invoke `session.rollback()` once for the synchronization transaction
only and return the safe result. The previously committed catalog row
MUST NOT be rolled back.

#### Scenario: Catalog services do not call sync or own transactions

- **WHEN** any catalog service module is inspected
  (`ProductoService`, `CategoriaProductoService`, `PresentacionService`,
  `ProductoPresentacionService`, `ProductoAliasService`)
- **THEN** the module does NOT import
  `CatalogEmbeddingSynchronizationService` or any sync entry point
- **AND** the module does NOT call `session.commit()`,
  `session.rollback()`, `session.close()`, or `session.begin()`
- **AND** no sync invocation is added inside any catalog service method

#### Scenario: Caller orchestrates commit then sync then commit-or-rollback

- **WHEN** the router / CLI / orchestrator runs a catalog mutation
  boundary end to end
- **THEN** `session.commit()` is invoked exactly once after the
  catalog service returns and before the sync runs
- **AND** the synchronization service is then invoked through the
  narrowest-scope entry point with the captured scope
- **AND** `session.commit()` is invoked exactly once on success
- **OR** `session.rollback()` is invoked exactly once when the
  synchronization raises an unhandled `SQLAlchemyError`
- **AND** the `get_session` generator remains the sole owner of
  `session.close()` in its `finally`

#### Scenario: Catalog commit precedes sync

- **WHEN** the router / CLI / orchestrator runs a catalog mutation
  boundary end to end
- **THEN** the SQLAlchemy session is committed exactly once after the
  catalog row is staged and before the sync is invoked
- **AND** the synchronization service receives a session whose catalog
  row is already visible to subsequent reads

#### Scenario: Ollama failure does not roll back the catalog

- **WHEN** the embedding client raises `EmbeddingClientError` during
  synchronization
- **THEN** the catalog row is NOT rolled back
- **AND** `session.rollback()` is NOT called by the caller for the
  catalog transaction
- **AND** the returned result reports `failed>0` and
  `synchronization_failed=False`

#### Scenario: Unhandled error rolls back only the sync transaction

- **WHEN** the synchronization raises an unhandled
  `sqlalchemy.exc.SQLAlchemyError`
- **THEN** `session.rollback()` is called exactly once by the caller
  for the synchronization transaction only
- **AND** the catalog row remains committed
- **AND** the returned result has `synchronization_failed=True`,
  `attempted=False`, and every counter `0`

### Requirement: Scope resolution is narrowest valid

The synchronization service SHALL resolve the narrowest valid scope for
each catalog mutation. The mapping SHALL be:

- product name / description / active / available change →
  every `producto_presentacion` whose `id_producto` matches the
  changed product
- category name / active change → every `producto_presentacion` whose
  parent product belongs to the changed category
- presentation code / description / active change → every
  `producto_presentacion` whose `id_presentacion` matches the changed
  presentation
- product-presentation active / available change → the single changed
  `producto_presentacion`
- product-wide alias create / update / activate / text / delete →
  every `producto_presentacion` whose `id_producto` matches the alias
- presentation-specific alias create / update / activate / text / delete
  → the single `producto_presentacion` whose id matches the alias

The service SHALL NOT reindex the entire commerce when a narrower scope
is available. The service SHALL NOT reindex a product when the changed
field is not part of any semantic document and does not change the
catalog activity chain.

#### Scenario: Product name change reindexes all its presentations

- **WHEN** `synchronize_producto(7)` is called and product 7 has three
  active `producto_presentaciones` (ids 31, 32, 33)
- **THEN** the indexer is called once per presentation
  (`id_producto_presentacion=31`, `id_producto_presentacion=32`,
  `id_producto_presentacion=33`)
- **AND** the aggregated counter `created + updated + unchanged` equals
  the sum of the three calls' counter values

#### Scenario: Product availability flip reindexes its presentations

- **WHEN** product 7's `disponible` flag changes from `True` to `False`
- **THEN** the service treats this as an embedding-relevant product
  change and reindexes presentations 31, 32, 33
- **AND** the embeddings carry the new availability-derived text

#### Scenario: Category name change reindexes only that category's products

- **WHEN** `synchronize_categoria(5)` is called and category 5 owns
  products 7, 8, 9, and unrelated category 6 owns product 10
- **THEN** the indexer is called for the presentations of products 7, 8,
  9 only
- **AND** the presentations of product 10 are NOT reindexed

#### Scenario: Presentation code change reindexes only linked product-presentations

- **WHEN** `synchronize_presentacion(12)` is called and presentation 12
  is referenced by two `producto_presentaciones` (ids 31, 45)
- **THEN** the indexer is called for ids 31 and 45
- **AND** other presentations that reference a different `id_presentacion`
  are NOT reindexed

#### Scenario: Product-presentation flag change reindexes only itself

- **WHEN** `synchronize_producto_presentacion(31)` is called
- **THEN** the indexer is called once with
  `id_producto_presentacion=31`
- **AND** no other presentation is reindexed

#### Scenario: Product-wide alias change reindexes every presentation of the product

- **WHEN** `synchronize_alias(42)` is called (alias still exists — used
  for create / update text / activate / deactivate paths) and alias 42
  has `id_producto=7, id_producto_presentacion=None` and product 7 owns
  three presentations
- **THEN** the indexer is called once per presentation of product 7
  (ids 31, 32, 33)
- **AND** the aggregated counter covers all three presentations
- **NOTE** post-delete synchronization does NOT use
  `synchronize_alias(id_alias)`; the orchestrator carries the captured
  `id_producto` forward and calls `synchronize_producto(7)` instead

#### Scenario: Presentation-specific alias change reindexes only its presentation

- **WHEN** `synchronize_alias(43)` is called and alias 43 has
  `id_producto=7, id_producto_presentacion=31`
- **THEN** the indexer is called once with
  `id_producto_presentacion=31`
- **AND** no other presentation of product 7 is reindexed

#### Scenario: Empty scope short-circuits without Ollama

- **WHEN** `synchronize_producto(7)` is called and product 7 owns zero
  `producto_presentaciones`
- **THEN** the result has `attempted=False`, every counter `0`,
  `synchronization_failed=False`
- **AND** the embedding client is NOT called

### Requirement: Repository scope-resolution reads are bounded and read-only

The repository methods used by the synchronization service for scope
resolution SHALL be read-only (`SELECT` statements only), SHALL NOT call
`session.commit`, `session.rollback`, `session.close`, or `session.begin`,
SHALL use bounded `select()` queries (e.g., `select(ProductoPresentacion.id)
.where(...)`), and SHALL NOT eager-load unrelated collections. The
methods SHALL be the minimum required to resolve:

- `list_producto_presentacion_ids_by_producto(id_producto) -> list[int]`
- `list_producto_presentacion_ids_by_categoria(id_categoria) -> list[int]`
- `list_producto_presentacion_ids_by_presentacion(id_presentacion) -> list[int]`
- `list_producto_presentacion_ids_by_alias(id_alias) -> list[int]`
  (returns either the single `id_producto_presentacion` or all
  `id_producto_presentacion` for the alias's `id_producto`)

#### Scenario: Scope resolution returns ids only

- **WHEN** `list_producto_presentacion_ids_by_producto(7)` is called
- **THEN** the result is a list of integer ids and the repository
  performs a bounded `select(ProductoPresentacion.id).where(...)` query
- **AND** no full `ProductoPresentacion` row is loaded into memory

#### Scenario: Scope resolution is read-only

- **WHEN** any scope-resolution repository method is called
- **THEN** the method does NOT issue `INSERT`, `UPDATE`, or `DELETE`
  statements
- **AND** the method does NOT call `session.commit`, `session.rollback`,
  `session.close`, or `session.begin`

### Requirement: Caller invokes sync only when an embedding-relevant field changed

Catalog services SHALL NOT decide whether to synchronize. The router /
CLI / orchestrator SHALL invoke the synchronization service ONLY when
the catalog mutation touched at least one embedding-relevant field. For
each catalog entity, the embedding-relevant field set SHALL be:

- `Producto`: `nombre`, `descripcion`, `activo`, `disponible`
- `CategoriaProducto`: `descripcion`, `activo`
- `Presentacion`: `codigo`, `descripcion`, `activo`
- `ProductoPresentacion`: `activo`, `disponible`
- `ProductoAlias`: `alias`, `activo`, scope transitions
  (create / update text / activate / deactivate / delete)

Mutations that touch only unrelated fields (e.g., `Producto.orden`)
SHALL NOT trigger synchronization. The catalog service MUST NOT be
modified to make this decision on the caller's behalf.

#### Scenario: Unrelated product field change does not trigger sync

- **WHEN** a product's `orden` changes
- **THEN** the orchestrator does NOT invoke
  `CatalogEmbeddingSynchronizationService`
- **AND** the catalog service returns without invoking the sync
- **AND** no Ollama call is issued

#### Scenario: Embedding-relevant product field change triggers sync

- **WHEN** a product's `nombre` changes
- **THEN** the orchestrator invokes
  `CatalogEmbeddingSynchronizationService.synchronize_producto(id_producto)`
  after the catalog commit
- **AND** the affected presentations are reindexed through the existing
  4.6 pipeline

#### Scenario: Embedding-relevant alias change triggers sync

- **WHEN** an alias is created, updated (text), activated, or
  deactivated
- **THEN** the orchestrator invokes
  `CatalogEmbeddingSynchronizationService.synchronize_alias(id_alias)`
  after the catalog commit
- **AND** the existing 4.6 stale reconciliation marks the obsolete
  document `stale` on deactivation
- **NOTE** alias deletion is governed separately by the "Alias deletion
  captures scope before deletion" requirement below; it does NOT use
  `synchronize_alias(id_alias)`

### Requirement: Alias deletion captures scope before deletion

Before the alias is deleted, `ProductoAliasService.delete` SHALL
capture from the alias row:

- `id_producto`
- `id_producto_presentacion`, when present

The captured scope SHALL be exposed on the service return value
(extension of the existing return shape; no new endpoint, no new
exception). After the catalog deletion is committed, the orchestrator
SHALL invoke synchronization using ONLY the captured scope:

- presentation-specific alias →
  `synchronize_producto_presentacion(captured_id_producto_presentacion)`
- product-wide alias →
  `synchronize_producto(captured_id_producto)`

The synchronization service SHALL NEVER be invoked with the deleted
alias's `id_alias`. The synchronization service SHALL NOT attempt to
resolve a deleted alias through `id_alias`. The post-delete path
bypasses `synchronize_alias(id_alias)` entirely and uses the narrower
`synchronize_producto` or `synchronize_producto_presentacion` entry
point with the captured scope. `synchronize_alias(id_alias)` remains
valid only for create / update text / activate / deactivate, where the
alias row still exists.

#### Scenario: Product-wide alias deletion synchronizes the product

- **WHEN** an alias with `id_producto=7, id_producto_presentacion=None`
  is being deleted
- **THEN** `ProductoAliasService.delete` captures `id_producto=7` and
  `id_producto_presentacion=None` from the alias row BEFORE the
  deletion is staged
- **AND** the service return value exposes that captured scope
- **AND** after the catalog commit, the orchestrator invokes
  `synchronize_producto(7)` using the captured `id_producto`
- **AND** `synchronize_alias(id_alias)` is NOT invoked for post-delete
  synchronization

#### Scenario: Presentation-specific alias deletion synchronizes that presentation

- **WHEN** an alias with `id_producto=7, id_producto_presentacion=31`
  is being deleted
- **THEN** `ProductoAliasService.delete` captures `id_producto=7` and
  `id_producto_presentacion=31` from the alias row BEFORE the deletion
  is staged
- **AND** the service return value exposes that captured scope
- **AND** after the catalog commit, the orchestrator invokes
  `synchronize_producto_presentacion(31)` using the captured
  `id_producto_presentacion`
- **AND** `synchronize_alias(id_alias)` is NOT invoked for post-delete
  synchronization

#### Scenario: Sync does not resolve a deleted alias through id_alias

- **WHEN** the post-delete synchronization is invoked
- **THEN** the synchronization service does NOT receive a call to
  `synchronize_alias(id_alias)` for the deleted alias
- **AND** the synchronization service is not given access to
  `id_alias` as input for post-delete synchronization
- **AND** no SQL is issued that selects from the deleted alias row

### Requirement: Sync preserves the 4.7 manual reindex endpoint

The Subphase 4.7 `POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
and `GET .../status` endpoints SHALL remain reachable and unchanged when
the `Settings.enable_local_admin_endpoints` flag is enabled. The
synchronization service SHALL NOT modify the route handler, the admin
service, the reindex request schema, or the status response schema. The
synchronization service SHALL NOT issue HTTP calls.

#### Scenario: Manual reindex endpoint remains reachable

- **WHEN** `Settings.enable_local_admin_endpoints` is `true` and a client
  calls `POST /admin/comercios/1/product-embeddings/reindex`
- **THEN** the route handler delegates to the 4.6 seeder exactly as
  Subphase 4.7 defined
- **AND** the synchronization service is not invoked through this path

#### Scenario: Sync is decoupled from the admin router

- **WHEN** the synchronization service module is inspected
- **THEN** it does NOT import the admin router, the admin service, the
  reindex request schema, or the status response schema
- **AND** it does NOT issue HTTP calls
