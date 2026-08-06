# Capability: product-embedding-admin-endpoints

## Purpose

TBD

## Requirements

### Requirement: Local-admin endpoints expose indexing and status without duplicating logic

The system SHALL expose two local administrative FastAPI endpoints at `POST /admin/comercios/{comercio_id}/product-embeddings/reindex` and `GET /admin/comercios/{comercio_id}/product-embeddings/status` that delegate to the existing Subphase 4.6 `ProductoPresentacionEmbeddingIndexer` / `ProductoPresentacionEmbeddingSeeder` / `ProductoPresentacionEmbeddingRepository` / `ProductoPresentacionEmbeddingIndexRepository` through their public service surface. The endpoints SHALL NOT duplicate batching, hash comparison, stale / inactive / failed handling, dry-run classification, or any embedding-client orchestration. The route handlers SHALL receive the SQLAlchemy session through `Depends(get_session)` (the existing `backend.dependencies.get_session` generator, which is the sole owner of `session.close()` in its `finally`) and SHALL own only the inner transaction boundary: `session.commit()` once after a completed real reindex, no commit on `dry_run`, `session.rollback()` once on an unhandled exception. The route handlers SHALL NEVER call `session.close()`; the service and repository layers SHALL NOT call `commit`, `rollback`, `close`, or `begin`. SQLAlchemy queries SHALL live only in repositories.

#### Scenario: Reindex delegates the run to the existing 4.6 seeder

- **WHEN** the reindex endpoint accepts a request against an existing comercio
- **THEN** the endpoint delegates the run to `ProductoPresentacionEmbeddingSeeder.run(...)` with the commerce scope and accepted options forwarded
- **AND** the response carries the six counters (`created`, `updated`, `unchanged`, `stale`, `inactive`, `failed`) plus the per-presentation outcomes from `SeedingResult.outcomes`

#### Scenario: Status delegates the read to the new status repository

- **WHEN** the status endpoint accepts a request against an existing comercio
- **THEN** the endpoint delegates the read to the new `ProductoPresentacionEmbeddingStatusRepository`
- **AND** the response carries commerce id, configured `embedding_model`, configured `embedding_dimension`, total rows, counts by `embedding_status` (pending / ready / failed / stale / inactive), active row count, count of rows with non-null `last_error`, and counts by `source_type`

#### Scenario: Reindex endpoint is wired through `Depends(get_session)`

- **WHEN** the reindex endpoint is invoked
- **THEN** the route handler declares `session: Annotated[Any, Depends(get_session)]` (the router imports `Annotated, Any` from `typing` and does NOT import `sqlalchemy` solely for the session type annotation)
- **AND** the route handler does NOT import `_SessionLocal` or call `session.close()` directly
- **AND** the route handler relies on `get_session`'s generator `finally` to close the session once the request finishes

#### Scenario: Status endpoint is wired through `Depends(get_session)`

- **WHEN** the status endpoint is invoked
- **THEN** the route handler declares `session: Annotated[Any, Depends(get_session)]` (the router imports `Annotated, Any` from `typing` and does NOT import `sqlalchemy` solely for the session type annotation)
- **AND** the route handler does NOT import `_SessionLocal` or call `session.close()` directly
- **AND** the route handler performs no `session.commit()` and no `session.rollback()` on the happy path; the `get_session` generator still closes the session in its `finally`

### Requirement: Local-admin endpoints are gated by a settings flag

The system SHALL gate every local-admin endpoint behind a `Settings.enable_local_admin_endpoints` field (env var `ENABLE_LOCAL_ADMIN_ENDPOINTS`, default `false`, parsed through `_bool_env` like every other boolean setting). When the flag is `false`, both endpoints SHALL return `404` so the surface is indistinguishable from a missing route. The gate SHALL be the first line of every endpoint function so no service work happens when the flag is `false`. The system SHALL NOT implement users, roles, JWT, OAuth, API keys, sessions, or any other authentication mechanism in this subphase — the flag is the only protection and is intended for local development only.

#### Scenario: Endpoints return 404 when the gate is disabled

- **WHEN** `Settings.enable_local_admin_endpoints` is `false`
- **AND** a client calls `POST /admin/comercios/1/product-embeddings/reindex` or `GET /admin/comercios/1/product-embeddings/status`
- **THEN** the endpoint returns `404`
- **AND** no service function is called
- **AND** no SQLAlchemy query is issued

#### Scenario: Endpoints are reachable when the gate is enabled

- **WHEN** `Settings.enable_local_admin_endpoints` is `true`
- **THEN** `POST /admin/comercios/{comercio_id}/product-embeddings/reindex` and `GET /admin/comercios/{comercio_id}/product-embeddings/status` are reachable
- **AND** the gate participates in OpenAPI metadata so operators can see whether the surface is exposed

### Requirement: Reindex endpoint validates the commerce and scope filters

The reindex endpoint SHALL validate that `comercio_id` exists (via the existing `ComercioService.get_by_id(...)`) and SHALL return `404` when the comercio does not exist. When optional `producto_id` or `producto_presentacion_id` are supplied in the JSON body, the endpoint SHALL validate that they belong to the given `comercio_id` (using the parent-chain joins the 4.6 index repository already exposes) and SHALL return `400` with a safe error message when the scope is invalid. When `batch_size` is supplied, the endpoint SHALL validate that it is a positive integer and SHALL apply it through `dataclasses.replace(settings, embedding_batch_size=batch_size)` on the frozen `Settings` — the same override path the 4.6 CLI uses. The endpoint SHALL NOT modify the `OllamaEmbeddingClient` constructor.

#### Scenario: Missing comercio returns 404

- **WHEN** the reindex endpoint receives a request with `comercio_id` that does not exist
- **THEN** the endpoint returns `404`
- **AND** no indexer, seeder, or repository call is issued

#### Scenario: Invalid scope returns 400

- **WHEN** the reindex endpoint receives a request whose `producto_id` does not belong to the supplied `comercio_id`
- **THEN** the endpoint returns `400` with a safe message that does not leak the offending id or other internal details

#### Scenario: Non-positive batch size returns 400

- **WHEN** the reindex endpoint receives a request whose `batch_size` is `0` or negative
- **THEN** the endpoint returns `400` before any indexer, seeder, embedding client, or Ollama call is issued

### Requirement: Reindex endpoint delegates to the 4.6 seeder and respects dry-run and force

The reindex endpoint SHALL accept `dry_run`, `force`, and the optional scope filters, SHALL forward them to the existing `ProductoPresentacionEmbeddingSeeder.run(...)`, and SHALL return the result counters without exposing full embedding vectors, customer messages, internal exception traces, or the persisted `Settings`. When `dry_run=True`, the endpoint SHALL call `seeder.run(...)` with `dry_run=True` and SHALL NOT call `session.commit()`; when `dry_run=False` and the seeder returns `failed==0`, the endpoint SHALL call `session.commit()` once; when `dry_run=False` and the seeder returns `failed>0`, the endpoint SHALL still call `session.commit()` once and SHALL return a successful HTTP response (`200`) whose body exposes the counters — recoverable embedding failures MUST NOT be re-raised as unhandled server exceptions. When the seeder raises an unexpected exception (NOT a recoverable embedding failure), the endpoint SHALL call `session.rollback()` once and SHALL propagate the exception so FastAPI returns `500` with the default body.

#### Scenario: Reindex dry-run performs no commit

- **WHEN** the reindex endpoint receives a request with `dry_run=True`
- **THEN** the endpoint returns `200` with the summary counters
- **AND** `session.commit()` is NOT called
- **AND** `session.rollback()` is NOT called
- **AND** no `INSERT` / `UPDATE` is issued against `producto_presentacion_embeddings`

#### Scenario: Reindex completed real run commits once

- **WHEN** the reindex endpoint receives a request with `dry_run=False`
- **AND** the seeder returns `failed=0`
- **THEN** the endpoint returns `200` with the summary counters
- **AND** `session.commit()` is called exactly once
- **AND** `session.rollback()` is NOT called
- **AND** `session.close()` is NOT called from the route handler
- **AND** the `get_session` generator's `finally` closes the session once the request finishes

#### Scenario: Reindex recoverable embedding failures return 200 with counters

- **WHEN** the reindex endpoint receives a request with `dry_run=False`
- **AND** the seeder returns `failed>0` because `embed_documents` raised `EmbeddingClientError` for a batch and the documents transitioned to `failed`
- **THEN** the endpoint returns `200` with the summary counters, including the populated `failed` count
- **AND** `session.commit()` is called exactly once (the failed rows persist)
- **AND** no embedding vectors, no internal exception traces, and no unhandled server exceptions are surfaced

#### Scenario: Reindex unhandled failure rolls back

- **WHEN** the reindex endpoint receives a request with `dry_run=False`
- **AND** the seeder raises an unexpected `SQLAlchemyError`
- **THEN** `session.rollback()` is called exactly once
- **AND** `session.close()` is NOT called from the route handler
- **AND** the exception propagates so FastAPI returns `500`
- **AND** the `get_session` generator's `finally` still closes the session once the response is sent
- **AND** the response body does not leak the exception details

### Requirement: Status endpoint exposes a commerce-scoped summary without vectors

The status endpoint SHALL return a commerce-scoped summary over `producto_presentacion_embeddings`. The response SHALL include `comercio_id`, the configured `embedding_model`, the configured `embedding_dimension`, total rows, counts by `embedding_status` (pending / ready / failed / stale / inactive), active row count (`activo = true`), count of rows with non-null `last_error`, and counts by `source_type` (canonical / description / alias / combined). The response SHALL NOT include complete embedding vectors, customer messages, credentials, internal exception traces, source text, normalized text, or content hashes. SQLAlchemy queries SHALL live only in the new `ProductoPresentacionEmbeddingStatusRepository` and SHALL NOT be issued from the router or service layer.

#### Scenario: Status is commerce-isolated

- **WHEN** the status endpoint receives a request for `comercio_id=1`
- **THEN** the response counters only reflect rows whose `CategoriaProducto.id_comercio == 1`
- **AND** rows for other comercios are NOT counted

#### Scenario: Status counters cover every embedding_status

- **WHEN** the status endpoint receives a request against a comercio whose rows cover every status
- **THEN** the response carries the `pending`, `ready`, `failed`, `stale`, and `inactive` counts (each possibly `0`)
- **AND** the totals (sum of counts) equal the reported `total` when no row is double-counted

#### Scenario: Status response never exposes vectors

- **WHEN** the status endpoint returns a response
- **THEN** the response payload does NOT contain any field that mirrors the `vector` column
- **AND** the response payload does NOT contain `source_text`, `normalized_text`, `content_hash`, `last_error`, `fecha_alta`, or `fecha_ultima_modificacion`
