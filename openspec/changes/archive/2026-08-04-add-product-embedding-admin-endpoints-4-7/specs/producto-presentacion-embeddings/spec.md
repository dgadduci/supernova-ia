## ADDED Requirements

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
