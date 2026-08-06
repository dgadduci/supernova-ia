# Capability: producto-presentacion-embeddings

## Purpose

TBD

## Requirements

### Requirement: Product-presentation embedding persistence

The system SHALL define a persistence model and database table for per-semantic-document embeddings associated with a `ProductoPresentacion`. Each row SHALL include a primary key, a non-null `id_producto_presentacion` foreign key to `producto_presentaciones.id` with `ON DELETE CASCADE`, a nullable `vector` with the configured embedding dimension (non-null when `embedding_status='ready'`, see `ready_vector_chk`), a non-null embedding model identifier, a non-null `source_type` drawn from the closed set `canonical | description | alias | combined`, a nullable `source_record_id` integer (the alias row id for `alias` rows, `NULL` for every other source type — see `source_record_id_alias_chk`), a non-null `source_text` (`Text`, non-empty after trimming), a non-null `normalized_text` (`Text`, non-empty after trimming), a non-null `content_hash` (`String(64)`, lowercase 64-character hex SHA-256 — see `content_hash_chk`), a non-null `embedding_status` drawn from the closed set `pending | ready | failed | stale | inactive`, a non-null `activo` boolean (default `True`, server-default `"true"`), a nullable `last_error` (`Text`), and lifecycle timestamps. Uniqueness SHALL be enforced through two PostgreSQL partial unique indexes: `(id_producto_presentacion, modelo, source_type) WHERE source_record_id IS NULL` (covers `canonical` / `description` / `combined`, one slot each per presentation per model) and `(id_producto_presentacion, modelo, source_type, source_record_id) WHERE source_record_id IS NOT NULL` (covers `alias`, one slot per alias per presentation per model). The legacy `(id_producto_presentacion, modelo)` aggregate uniqueness rule SHALL NOT exist.

#### Scenario: Embedding exposes required persisted fields

- **WHEN** the embedding model and table metadata are inspected
- **THEN** the table exposes the product-presentation foreign key, the `vector` column with the configured dimension (nullable when `embedding_status <> 'ready'`), the `modelo` identifier, `source_type`, `source_record_id`, `source_text`, `normalized_text`, `content_hash`, `embedding_status`, `activo`, `last_error`, and lifecycle timestamps
- **AND** the product-presentation foreign key is indexed and configured with `ON DELETE CASCADE`

#### Scenario: Embeddings are unique per document identity

- **WHEN** a second embedding is persisted for the same `(id_producto_presentacion, modelo, source_type, source_record_id)` tuple
- **THEN** the persistence boundary rejects the duplicate row or updates the existing row through the defined `create_or_update_document` operation
- **AND** the rejection is enforced by the two partial unique indexes (one for `source_record_id IS NULL`, one for `source_record_id IS NOT NULL`)

#### Scenario: Different model identifiers coexist for the same document

- **WHEN** an embedding is persisted for `(id_producto_presentacion=31, modelo="all-minilm:latest", source_type="canonical", source_record_id=None)` and another for the same presentation with `modelo="bge-small:latest"`
- **THEN** both rows persist because the `modelo` column is part of the partial unique index
- **AND** the same applies for alias rows whose `(source_type="alias", source_record_id=...)` differs only in `modelo`

#### Scenario: source_type membership is enforced

- **WHEN** the table-level constraints are inspected
- **THEN** a `CHECK` constraint named `source_type_chk` enforces `source_type IN ('canonical','description','alias','combined')`
- **AND** any insert with a value outside this set is rejected by the database

#### Scenario: alias rows require a non-null source_record_id

- **WHEN** the table-level constraints are inspected
- **THEN** a `CHECK` constraint named `source_record_id_alias_chk` enforces `(source_type = 'alias' AND source_record_id IS NOT NULL) OR (source_type <> 'alias' AND source_record_id IS NULL)`
- **AND** an `alias` row with `source_record_id IS NULL` is rejected
- **AND** a `canonical` / `description` / `combined` row with `source_record_id IS NOT NULL` is rejected

#### Scenario: ready rows require a non-null vector

- **WHEN** the table-level constraints are inspected
- **THEN** a `CHECK` constraint named `ready_vector_chk` enforces `embedding_status <> 'ready' OR vector IS NOT NULL`
- **AND** an insert or update with `embedding_status='ready'` and `vector IS NULL` is rejected
- **AND** rows with `embedding_status` in `pending | failed | stale | inactive` MAY have `vector IS NULL`

#### Scenario: content_hash is a lowercase 64-character hex digest

- **WHEN** the table-level constraints are inspected
- **THEN** a `CHECK` constraint named `content_hash_chk` enforces `content_hash ~ '^[0-9a-f]{64}$'`
- **AND** any insert with uppercase, wrong length, or non-hex characters is rejected

#### Scenario: source_text and normalized_text are non-empty

- **WHEN** the table-level constraints are inspected
- **THEN** `CHECK` constraints named `source_text_nonempty_chk` and `normalized_text_nonempty_chk` enforce `length(btrim(source_text)) > 0` and `length(btrim(normalized_text)) > 0` respectively
- **AND** any insert with empty-after-trimming text is rejected

### Requirement: Idempotent embedding persistence operations

The system SHALL provide an application persistence boundary that stores, updates, retrieves, and reconciles per-semantic-document embeddings by the full document tuple `(id_producto_presentacion, modelo, source_type, source_record_id)`. The boundary SHALL expose `create_or_update_document(...)`, `record_failed_document(...)`, `find_by_document(...)`, `list_by_producto_presentacion_and_model(...)`, `list_by_comercio(...)`, `list_by_producto(...)`, `list_by_producto_presentacion(...)`, `mark_status(...)`, `mark_stale(...)`, and `mark_inactive(...)`. The hash comparison and the `embedding_status` / `activo` / `vector` / `force` checks SHALL be performed by the service (NOT the repository); the repository SHALL perform only SQLAlchemy reads and writes (`insert_document`, `update_document`, `find_by_document`, `list_*`, `mark_status`). The `update_document(...)` operation persists the complete document metadata (`source_text`, `normalized_text`, `content_hash`, `vector`, `embedding_status`, `activo`, `last_error`) and advances `fecha_ultima_modificacion`. The boundary SHALL NOT call `commit`, `rollback`, `close`, or `begin`. A row whose stored `content_hash` matches the incoming `content_hash`, AND whose `embedding_status='ready'`, AND whose `activo=True`, AND whose `vector` is present and dimension-valid, AND when `force=False`, SHALL be returned as-is with no vector update, no `last_error` change, and no `fecha_ultima_modificacion` advance.

#### Scenario: New embedding document is persisted

- **WHEN** a valid `(id_producto_presentacion, modelo, source_type, source_record_id)`, vector of the configured dimension, `source_text`, `normalized_text`, and `content_hash` are submitted
- **THEN** one embedding row is created and can be retrieved by the document tuple

#### Scenario: Existing embedding document is updated idempotently

- **WHEN** a valid vector with a different `content_hash` is submitted for an existing row identified by the document tuple
- **THEN** no duplicate row is created
- **AND** the stored vector is replaced, `embedding_status` is set to `ready`, `last_error` is cleared, and `fecha_ultima_modificacion` is updated

#### Scenario: Unchanged embedding document is preserved only when every condition holds

- **WHEN** `create_or_update_document` is called with `force=False` and the stored row has the same `content_hash` as the incoming `content_hash`, AND `embedding_status='ready'`, AND `activo=True`, AND the stored `vector` is present and dimension-valid
- **THEN** the row is returned unchanged: the vector is not rewritten, `embedding_status` remains `ready`, `activo` remains `True`, `last_error` remains cleared, `fecha_ultima_modificacion` is not advanced
- **WHEN** ANY of those five conditions fails (hashes differ, status is `failed` / `stale` / `inactive`, `activo` is `False`, stored vector is missing or dimension-mismatched, or `force=True`)
- **THEN** the row is updated through `repository.update_document(...)` and `last_error` is cleared, `embedding_status` transitions to `'ready'`, `activo` is set to `True`, and `fecha_ultima_modificacion` is advanced

#### Scenario: Failed embedding document records last_error without losing the previous vector

- **WHEN** a document with `embedding_status='ready'` is reconciled and the embedding client raises a domain error
- **THEN** the existing row is updated to `embedding_status='failed'`, `last_error=<safe message>`, the previous vector is preserved when present, and `fecha_ultima_modificacion` is updated
- **WHEN** no row exists for the document yet
- **THEN** a new row is inserted with `vector=NULL`, `embedding_status='failed'`, `last_error=<safe message>`, and the supplied `source_text` / `normalized_text` / `content_hash` so a subsequent re-run can retry

#### Scenario: record_failed_document persists metadata for a missing document

- **WHEN** `service.record_failed_document(document, error_message, *, modelo)` is called and no row exists for the document tuple
- **THEN** `repository.insert_document(...)` is called with `vector=NULL`, `embedding_status='failed'`, `activo=True`, a sanitized `last_error`, and the supplied `source_text`, `normalized_text`, `content_hash`, `modelo`
- **AND** the operation does NOT increment a successful `created` or `updated` counter; only the `failed` counter advances

#### Scenario: record_failed_document preserves the previous vector for an existing row

- **WHEN** `service.record_failed_document(document, error_message, *, modelo)` is called and a row already exists for the document tuple
- **THEN** `repository.update_document(...)` is called with the supplied `source_text`, `normalized_text`, `content_hash`, `embedding_status='failed'`, `activo=True`, sanitized `last_error`, and the previous `vector` (unchanged) and `fecha_alta` (unchanged)
- **AND** the previous vector is preserved
- **AND** the operation does NOT increment a successful `created` or `updated` counter; only the `failed` counter advances

#### Scenario: Invalid vector dimension is rejected

- **WHEN** a vector whose length differs from the configured embedding dimension is submitted
- **THEN** the persistence operation rejects it before creating or modifying a row

#### Scenario: Invalid embedding status transition is rejected

- **WHEN** `mark_status` is called to transition a row from `pending` to `stale`
- **THEN** the operation raises `InvalidEmbeddingStatusTransition`
- **WHEN** `mark_status` is called to transition a row from `pending` to `inactive`
- **THEN** the operation raises `InvalidEmbeddingStatusTransition`
- **WHEN** `mark_status` is called to transition a row from `ready` to `ready`
- **THEN** the operation succeeds (idempotent no-op)
- **WHEN** `mark_status` is called to transition a row from `stale` to `ready`
- **THEN** the operation succeeds (reactivation)
- **WHEN** `mark_status` is called to transition a row from `inactive` to `ready`
- **THEN** the operation succeeds (reactivation)
- **WHEN** `mark_status` is called to transition a row from `failed` to `ready`
- **THEN** the operation succeeds (recovery)

#### Scenario: Missing product presentation is rejected

- **WHEN** an embedding references a product-presentation identifier that does not exist
- **THEN** persistence rejects the operation without creating an orphan embedding row

### Requirement: pgvector extension availability

The database schema SHALL enable PostgreSQL's `vector` extension before creating the embedding vector column. Applying the migration to a supported PostgreSQL database SHALL make the extension available for the embedding table.

#### Scenario: Migration enables vector support

- **WHEN** the embedding migration is applied to a supported PostgreSQL database
- **THEN** the `vector` extension exists before the embedding table is created
- **AND** the embedding vector column is created with the configured dimension

#### Scenario: Product-presentation deletion cascades to embeddings

- **WHEN** a product presentation with persisted embeddings is deleted
- **THEN** all embeddings owned by that product presentation are deleted by the database cascade
- **AND** no orphan embedding rows remain

### Requirement: Embedding status state machine with reactivation paths

The system SHALL define a Python `class EmbeddingStatus(str, enum.Enum)` whose values ARE the lowercase strings (`'pending'`, `'ready'`, `'failed'`, `'stale'`, `'inactive'`) and SHALL store it in a `String(32)` column. The closed value set SHALL be enforced by a table-level `embedding_status_chk` (`CHECK (embedding_status IN ('pending','ready','failed','stale','inactive'))`). The state machine SHALL permit the following transitions:

- `pending → ready | failed | inactive`
- `ready → failed | stale | inactive` (and `ready → ready` is an idempotent no-op)
- `failed → ready | failed | stale | inactive` (recovery via a fresh successful embedding; preservation as obsolete or inactive when the catalog changes)
- `stale → ready | failed | inactive` (recovery when the document becomes generated again; preservation as inactive when the catalog changes)
- `inactive → ready | failed | stale` (recovery when the catalog is re-activated; preservation as obsolete when the builder no longer produces the document)

Any other transition SHALL be rejected with `InvalidEmbeddingStatusTransition`. `stale` and `inactive` are NOT permanently terminal; they preserve the row's vector and timestamps and may transition back to `ready` when the document is regenerated or the catalog is re-activated.

#### Scenario: EmbeddingStatus enum is exported with lowercase values

- **WHEN** the `EmbeddingStatus` enum and the embedding table metadata are inspected
- **THEN** the enum exposes `PENDING = "pending"`, `READY = "ready"`, `FAILED = "failed"`, `STALE = "stale"`, `INACTIVE = "inactive"`
- **AND** `EmbeddingStatus.READY == "ready"` (the Python value IS the lowercase string)
- **AND** the column type is `String(32)` and PostgreSQL stores the lowercase strings
- **AND** a table-level `embedding_status_chk` enforces the closed set; there is exactly one database representation

#### Scenario: embedding_status_chk rejects values outside the closed set

- **WHEN** an `INSERT` or `UPDATE` is attempted with `embedding_status` outside `'pending' | 'ready' | 'failed' | 'stale' | 'inactive'`
- **THEN** the database rejects the statement with an integrity error
- **AND** the rejection is enforced by the `embedding_status_chk` table-level `CHECK` constraint

#### Scenario: Forward transitions from pending are accepted

- **WHEN** `mark_status(row, READY)` is called on a row currently in `PENDING`
- **THEN** the operation succeeds
- **WHEN** `mark_status(row, FAILED)` is called on a row currently in `PENDING`
- **THEN** the operation succeeds
- **WHEN** `mark_status(row, INACTIVE)` is called on a row currently in `PENDING`
- **THEN** the operation succeeds (the catalog became inactive before generation finished)

#### Scenario: Reactivation from stale and inactive is accepted

- **WHEN** `mark_status(row, READY)` is called on a row currently in `STALE`
- **THEN** the operation succeeds and the row transitions back to `ready`
- **WHEN** `mark_status(row, READY)` is called on a row currently in `INACTIVE`
- **THEN** the operation succeeds and the row transitions back to `ready`
- **WHEN** `mark_status(row, READY)` is called on a row currently in `FAILED`
- **THEN** the operation succeeds and `last_error` is cleared

#### Scenario: Forbidden transitions are rejected

- **WHEN** `mark_status(row, STALE)` is called on a row currently in `PENDING`
- **THEN** the operation raises `InvalidEmbeddingStatusTransition`
- **WHEN** `mark_status(row, INACTIVE)` is called on a row currently in `PENDING`
- **THEN** the operation raises `InvalidEmbeddingStatusTransition`

### Requirement: Hash-based idempotency at the persistence boundary

The service SHALL use `content_hash` as the idempotency key for `create_or_update_document(document, vector, *, modelo, force=False)`. The hash comparison and the `embedding_status` / `activo` / `vector` / `force` checks are performed by the service, not by the repository. The service SHALL return `DocumentReconciliationOutcome.UNCHANGED` only when ALL of the following are true: the stored `content_hash` equals the incoming `content_hash`; the row's `embedding_status == 'ready'`; the row's `activo == True`; the row's `vector` is present and has the configured dimension; `force == False`. When all five conditions hold, the service returns the existing row without calling `repository.update_document(...)`, without changing `last_error`, and without advancing `fecha_ultima_modificacion`. Otherwise, when a row exists, the service delegates to `repository.update_document(row, *, source_text, normalized_text, content_hash, vector, embedding_status=READY, activo=True, last_error=None)` — the complete document metadata is persisted, `embedding_status` is set to `ready`, `activo` is set to `True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced; this path covers `failed → ready`, `stale → ready`, `inactive → ready`, and `--force` with an unchanged hash. When no row exists, the service delegates to `repository.insert_document(...)` with `embedding_status='ready'`, `activo=True`, `last_error=NULL`.

#### Scenario: Matching content_hash on a ready, active, valid row is a no-op

- **WHEN** `create_or_update_document` is called with `force=False` and the stored row has the same `content_hash`, `embedding_status='ready'`, `activo=True`, and a present, dimension-valid `vector`
- **THEN** the row's `vector`, `source_text`, `normalized_text`, `content_hash`, `embedding_status`, `activo`, and `last_error` are unchanged
- **AND** `fecha_ultima_modificacion` is not advanced
- **AND** no SQLAlchemy `UPDATE` is issued by the repository for that row
- **AND** the service returns `DocumentReconciliationOutcome.UNCHANGED`

#### Scenario: Force flag updates an unchanged ready document

- **WHEN** `create_or_update_document` is called with `force=True` and the stored row has the same `content_hash`, `embedding_status='ready'`, `activo=True`, and a present, dimension-valid `vector`
- **THEN** the service delegates to `repository.update_document(...)` so the row's `vector`, `source_text`, `normalized_text`, `content_hash` are rewritten, `embedding_status` is set to `ready`, `activo` is set to `True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced
- **AND** the service returns `DocumentReconciliationOutcome.UPDATED`

#### Scenario: Different content_hash triggers an update

- **WHEN** `create_or_update_document` is called with a different `content_hash` than the stored row
- **THEN** `repository.update_document(...)` is called with the supplied `source_text`, `normalized_text`, `content_hash`, `vector`, `embedding_status='ready'`, `activo=True`, `last_error=None` so the row's complete document metadata is persisted, `embedding_status` is set to `ready`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced
- **AND** the service returns `DocumentReconciliationOutcome.UPDATED`

#### Scenario: Failed, stale, and inactive rows return to ready after successful regeneration

- **WHEN** `create_or_update_document` is called for a document whose existing row is in `embedding_status='failed'`, `'stale'`, or `'inactive'`
- **THEN** the service delegates to `repository.update_document(...)` so the row's complete document metadata is persisted, `embedding_status` transitions to `'ready'`, `activo` is set to `True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced
- **AND** the service returns `DocumentReconciliationOutcome.UPDATED` for each of the three transitions (`failed → ready`, `stale → ready`, `inactive → ready`)

#### Scenario: Missing row triggers an insert

- **WHEN** `create_or_update_document` is called for a document tuple that has no stored row
- **THEN** `repository.insert_document(...)` is called with the supplied `vector`, `source_text`, `normalized_text`, `content_hash`, `embedding_status='ready'`, `last_error=NULL`, and `activo=True`
- **AND** the service returns `DocumentReconciliationOutcome.CREATED`

#### Scenario: Update persists source_text and normalized_text

- **WHEN** `repository.update_document(...)` is called for an existing row
- **THEN** the row's `source_text`, `normalized_text`, `content_hash`, `vector`, `embedding_status`, `activo`, `last_error`, and `fecha_ultima_modificacion` are all updated by the repository
- **AND** no other column is updated by the repository for that row

### Requirement: Stale document preservation with reactivation

The persistence boundary SHALL preserve documents that the builder no longer produces by transitioning them to `stale` instead of deleting them. When the indexer determines that an existing row's document tuple is no longer produced by the builder, it SHALL call `mark_stale(row)` to transition the row to `stale` (legal transitions: `ready → stale`, `failed → stale`). The row's `vector` (when present), `source_text`, `normalized_text`, `content_hash`, `fecha_alta`, and `fecha_ultima_modificacion` SHALL be preserved; only `embedding_status` and `fecha_ultima_modificacion` transition. When the document becomes generated again, the indexer may transition the row back to `ready` via `mark_status(row, READY)`.

#### Scenario: Obsolete alias is marked stale

- **WHEN** an alias document row exists in `ready` and the builder no longer produces that alias (the alias was deleted or deactivated)
- **THEN** the row is transitioned to `embedding_status='stale'`, the previous vector is preserved, and the row is not deleted

#### Scenario: Stale document can be reactivated

- **WHEN** a stale row exists and the builder starts producing the document again
- **THEN** the indexer calls `mark_status(row, READY)` and the row transitions back to `ready` (with a fresh successful embedding); the previous vector is replaced and `last_error` is cleared

### Requirement: Inactive catalog reconciliation with reactivation

The persistence boundary SHALL preserve embeddings whose owning catalog row becomes inactive by transitioning them to `inactive` instead of deleting them. When the indexer detects that a `ProductoPresentacion` (or any parent in the chain — `Producto`, `Presentacion`, `CategoriaProducto`) has `activo = false`, it SHALL call `mark_inactive(row)` to transition every row whose `id_producto_presentacion` belongs to that presentation to `inactive` (legal transitions: `ready → inactive`, `failed → inactive`, `stale → inactive`, `pending → inactive`). The row's `vector` (when present), `source_text`, `normalized_text`, `content_hash`, and lifecycle timestamps SHALL be preserved; only `embedding_status` and `fecha_ultima_modificacion` transition. When the catalog is re-activated, the indexer may transition the row back to `ready` via `mark_status(row, READY)`.

#### Scenario: Inactive producto_presentacion marks embeddings inactive

- **WHEN** `mark_inactive` is called for the rows of a `ProductoPresentacion` whose `activo = false`
- **THEN** every row for that presentation transitions from `ready` / `pending` / `failed` to `inactive`
- **AND** the previous vector (when present) is preserved
- **AND** the row is not deleted

#### Scenario: Reactivated catalog row can be re-indexed

- **WHEN** a `ProductoPresentacion` that was previously marked `inactive` is reactivated (`activo = true`)
- **THEN** the indexer may transition the `inactive` rows back to `ready` by calling `mark_status(row, READY)` after a successful re-embedding
- **AND** the reactivation requires a fresh successful embedding (the previous vector is replaced and `last_error` is cleared)

### Requirement: Local-admin gate setting is read at startup

The `Settings` dataclass SHALL expose `enable_local_admin_endpoints: bool` (env var `ENABLE_LOCAL_ADMIN_ENDPOINTS`, default `false`, parsed through `_bool_env`). The setting SHALL be loaded once at startup via `load_settings()` and SHALL participate in the same frozen-dataclass contract as every other `Settings` field (no in-place mutation, no late binding). When the setting is `false`, every local-admin endpoint SHALL return `404` so the surface is indistinguishable from a missing route; when the setting is `true`, the local-admin endpoints SHALL be reachable. The setting SHALL NOT introduce any users, roles, JWT, OAuth, API keys, or sessions — it is the only protection and is intended for local development only.

#### Scenario: Default value is false

- **WHEN** the application starts without an `ENABLE_LOCAL_ADMIN_ENDPOINTS` env var
- **THEN** `Settings.enable_local_admin_endpoints` is `false`
- **AND** every local-admin endpoint returns `404`

#### Scenario: Opt-in enables the endpoints

- **WHEN** the application starts with `ENABLE_LOCAL_ADMIN_ENDPOINTS=true`
- **THEN** `Settings.enable_local_admin_endpoints` is `true`
- **AND** the local-admin endpoints respond

### Requirement: Status repository exposes commerce-isolated aggregations

The new `ProductoPresentacionEmbeddingStatusRepository` SHALL expose per-status and per-source-type aggregations over `producto_presentacion_embeddings` for a given `comercio_id` and `modelo`. The aggregations SHALL join `ProductoPresentacionEmbedding` × `ProductoPresentacion` × `Producto` × `CategoriaProducto` and SHALL filter on `CategoriaProducto.id_comercio == id_comercio` so other comercios are NEVER counted. The repository SHALL support:

- `count_by_comercio(id_comercio, modelo) -> EmbeddingStatusCounts` — aggregate counts per `embedding_status` (pending / ready / failed / stale / inactive), plus `total`, `active` (rows whose `activo = true`), and `with_last_error` (rows whose `last_error IS NOT NULL`).
- `count_by_source_type(id_comercio, modelo) -> EmbeddingSourceTypeCounts` — aggregate counts per `source_type` (canonical / description / alias / combined).
- `list_by_comercio(id_comercio, modelo)` — thin wrapper that returns the underlying `ProductoPresentacionEmbedding` rows for the comercio through the existing 4.6 parent-chain join.

The repository SHALL NOT issue INSERT, UPDATE, or DELETE statements. The repository SHALL NOT call `commit`, `rollback`, `close`, or `begin`. The repository SHALL NOT import HTTP, FastAPI, the embedding client, the indexer, or the seeder. The repository SHALL use `func.count()` and `group_by(source_type)` so a single query answers the count questions.

#### Scenario: Count is commerce-isolated

- **WHEN** `count_by_comercio(1, modelo)` is called against a `producto_presentacion_embeddings` table that holds rows for comercio 1 and comercio 2
- **THEN** only rows whose `CategoriaProducto.id_comercio == 1` are counted
- **AND** rows for comercio 2 are NOT counted

#### Scenario: Source-type counts cover every source_type

- **WHEN** `count_by_source_type(comercio_id, modelo)` is called
- **THEN** the response carries the `canonical`, `description`, `alias`, and `combined` counts (each possibly `0`)
- **AND** the sum of the four counts does not exceed the `total` reported by `count_by_comercio(...)` (a single row contributes to exactly one source-type bucket)

#### Scenario: Repository is read-only

- **WHEN** the status repository module is inspected
- **THEN** the module does NOT import `INSERT`, `UPDATE`, or `DELETE` operations against `producto_presentacion_embeddings`
- **AND** the module does NOT call `session.commit()`, `session.rollback()`, `session.close()`, or `session.begin()`
- **AND** the module does NOT import FastAPI, HTTP, the embedding client, the indexer, the seeder, or any router
