## Context

Subphase 4.6 (`2026-08-04-seed-product-presentation-embeddings-4-6`) shipped the per-document embedding indexing pipeline:

- `ProductoPresentacionEmbeddingIndexer` runs the pure `ProductEmbeddingDocumentBuilder` over a commerce / producto / presentation scoped projection and reconciles every document through `ProductoPresentacionEmbeddingService.create_or_update_document(...)` / `record_failed_document(...)` / `mark_status(...)`.
- `ProductoPresentacionEmbeddingSeeder` wraps the indexer and exposes the `(created, updated, unchanged, stale, inactive, failed)` aggregate counters plus per-presentation outcomes.
- `backend/scripts/seed_product_presentation_embeddings.py` is the only runner today. It opens `_SessionLocal()`, instantiates the indexer / seeder, owns the outer transaction (`session.commit()` once on success, `session.rollback()` once on unhandled error, `session.close()` in `finally`), and never persists anything on `--dry-run`. The CLI remains the canonical owner of the explicit `_SessionLocal()` flow; the new HTTP endpoints reuse `backend.dependencies.get_session` instead, which is the same `_SessionLocal()` factory wrapped in a `try / yield / finally: session.close()` generator.
- `ProductoPresentacionEmbeddingRepository` (per-document SQLAlchemy reads / writes; no commit / rollback / close / begin) and `ProductoPresentacionEmbeddingIndexRepository` (commerce-scoped projection; the only place `Producto`, `CategoriaProducto`, `Presentacion`, and the applicable alias rows are joined) already expose every read the admin endpoints need.
- `Settings` (frozen dataclass) currently exposes the LLM and embedding settings, but no local-admin gate.
- `backend/main.py` registers every router in the project. There is no prior `admin` router convention.
- The embedding client constructor is `(settings, transport=None, clock=None)` and must remain unchanged. `--batch-size` is supplied to the CLI through `dataclasses.replace(settings, embedding_batch_size=args.batch_size)` on the frozen `Settings`; the new endpoint must use the same override path.

The new subphase 4.7 work adds two local-admin HTTP endpoints that delegate to the existing 4.6 surface without duplicating batching, hash comparison, stale / inactive handling, or failure semantics.

## Goals / Non-Goals

**Goals:**

- Add `POST /admin/comercios/{comercio_id}/product-embeddings/reindex` and `GET /admin/comercios/{comercio_id}/product-embeddings/status` under a new `backend/routers/admin_product_embeddings.py` router.
- Gate every route behind `Settings.enable_local_admin_endpoints` (default `False`, env var `ENABLE_LOCAL_ADMIN_ENDPOINTS`); when disabled, every route short-circuits to `404` so the surface is indistinguishable from a missing route.
- The reindex endpoint validates `comercio_id`, validates optional `producto_id`, `producto_presentacion_id`, `force`, `dry_run`, `batch_size` from the JSON body, delegates to the existing 4.6 services through their public surface, returns the six counters (`created` / `updated` / `unchanged` / `stale` / `inactive` / `failed`), and never exposes vectors / internal exception traces.
- The status endpoint returns a commerce-scoped summary (commerce id, configured `embedding_model`, configured `embedding_dimension`, total rows, per-`embedding_status` counts, active count, count with `last_error`, optional per-`source_type` counts) and never exposes vectors, customer messages, or unsafe internal details.
- Reuse the 4.3 / 4.6 repository surface for both new reads and writes; SQLAlchemy queries belong only in repositories.
- Use the smallest maintainable structure: router → admin service → 4.6 services / repositories → SQLAlchemy. The router receives the SQLAlchemy session through `Depends(get_session)` (the existing `backend.dependencies.get_session` generator, which owns `session.close()` in its `finally`) and owns only the inner transaction boundary (`commit` once after a completed real reindex, no `commit` on `dry_run`, `rollback` once on an unhandled exception); the 4.6 services retain their no-commit / no-rollback / no-close / no-begin contract; the admin service is the only place that instantiates `OllamaEmbeddingClient` / `ProductoPresentacionEmbeddingIndexer` / `ProductoPresentacionEmbeddingSeeder` (preferred through constructor / factory injection so tests substitute fakes).

**Non-Goals:**

- Real authentication / authorization; users; roles; JWT; OAuth; API keys; sessions.
- Background jobs; Celery; Redis; automatic catalog-change regeneration.
- Vector similarity search; HNSW; IVFFlat indexing; hybrid recognizer wiring; fuzzy recognizer changes.
- Subphase 4.8 or later work; migrations; changes to the persistence model; embedding client constructor changes; pure builder changes.
- Returning full embedding vectors; returning customer messages; leaking internal exception traces.
- Converting recoverable embedding failures into unhandled server exceptions (a successful HTTP response with `failed > 0` is allowed and expected).

## Decisions

### 1. Router layout: one new `admin_product_embeddings.py` router, registered in `backend/main.py`, using `Depends(get_session)`

There is no prior `admin` convention in the project (every existing router is named after the resource it serves). A single `admin_product_embeddings.py` router matches the per-resource convention used by `pedidos.py`, `clientes.py`, `incoming_messages.py`, etc. The router is `APIRouter(tags=["admin-product-embeddings"])` with no `prefix=` so the URL structure stays as written in the project.md (`/admin/comercios/{comercio_id}/product-embeddings/...`). Two routes: one `POST` for reindex, one `GET` for status. The router is registered with `app.include_router(admin_product_embeddings.router)` after the embedding-adjacent routers so the URL ordering stays stable.

Alternatives considered:

- A single shared `admin.py` router hosting every future admin endpoint. Rejected: over-engineering for two endpoints and creates a precedence risk when more endpoints land.
- Spread across two routers (`admin_product_embeddings_reindex.py`, `admin_product_embeddings_status.py`). Rejected: every other router in the project hosts every CRUD verb for one resource, so two routers for one resource breaks the convention.

### 2. Gate: `Settings.enable_local_admin_endpoints: bool = False`

Added to `backend/config/settings.py` as a fifth `bool` field with the `_bool_env("ENABLE_LOCAL_ADMIN_ENDPOINTS", False)` loader, mirroring `LLM_LOG_CONTENT`. The router reads `load_settings()` directly through a small `Annotated[bool, Depends(...)]` dependency so the gate participates in OpenAPI metadata (`responses={404: ...}`). The check is the first line of every endpoint function so a `404` is returned before any other work.

Alternative considered:

- Read the env var directly via `os.environ.get(...)` inside the route handler. Rejected: bypasses `Settings` and the standard env-loading path (`load_dotenv` in `backend/config/settings.py`), and the rest of the codebase already goes through `load_settings()`.
- Return `403` when disabled. Rejected: `404` makes the surface invisible by default, which is what `openspec/specs/project.md` §4.7 implies ("endpoints unavailable when disabled") and what the nine numbered test cases anticipate.

### 3. Service layer: thin `ProductoPresentacionEmbeddingAdminService` over the 4.6 services

The router delegates to a new `backend/services/producto_presentacion_embedding_admin_service.py` instead of calling `ProductoPresentacionEmbeddingSeeder` / `ProductoPresentacionEmbeddingIndexer` / `OllamaEmbeddingClient` directly. The service:

- Validates that `comercio_id` exists through `ComercioService.get_by_id(...)` (re-uses the existing 4.x commerce lookup).
- Validates that `producto_id` / `producto_presentacion_id`, when supplied, point at presentations under the given `comercio_id` (delegated to `ProductoPresentacionEmbeddingIndexRepository` which already joins the parent chain).
- Validates `batch_size` (positive integer when supplied) and propagates through `dataclasses.replace(settings, embedding_batch_size=batch_size)` on the frozen `Settings` — the same override path the 4.6 CLI uses.
- Owns the `OllamaEmbeddingClient` (constructor stays `(settings, transport=None, clock=None)`; the service does NOT extend the constructor), the `ProductoPresentacionEmbeddingIndexer`, and the `ProductoPresentacionEmbeddingSeeder`. These objects are accepted through constructor / factory injection so the embedding client can be swapped for a fake in tests without instantiating a real Ollama transport.
- Calls `seeder.run(...)` for reindex and lifts `SeedingResult` into the response DTO shape.
- For status, calls the new `ProductoPresentacionEmbeddingStatusRepository` (per-status / per-source-type aggregation) and lifts the rows into the response DTO shape.

The service NEVER calls `commit` / `rollback` / `close` / `begin` (verified by the boundary test). The service NEVER imports `sqlalchemy`, `fastapi`, or `requests`. The service NEVER issues raw SQLAlchemy queries — those live only in the repositories. The transaction boundary lives in the router.

Alternatives considered:

- Skip the service and call the seeder / repository / client directly from the router. Rejected: the routing layer must stay HTTP-only (boundary test) and the commerce / scope validation is non-trivial business logic.
- Embed the validation in the router. Rejected: validation belongs in the service per the project's existing routers (`ClienteService` validates, `CategoriaProductoService` validates, etc.).
- Inject the `OllamaEmbeddingClient` as an optional `transport=` argument through the existing constructor (which already accepts `transport=None`). Rejected: keeps the constructor signature unchanged, which is the explicit Subphase 4.6 contract; tests construct the fake client directly with the same signature.

### 4. Status repository: `ProductoPresentacionEmbeddingStatusRepository`

A new `backend/repositories/producto_presentacion_embedding_status_repository.py` exposes:

- `count_by_comercio(id_comercio, modelo) -> EmbeddingStatusCounts` — one query, `func.count()` filtered by `CategoriaProducto.id_comercio` and `EmbeddingStatus.<X>.value`, plus `func.count().filter(... activo.is_(True))` and `func.count().filter(... last_error.is_not(None))`.
- `count_by_source_type(id_comercio, modelo) -> dict[str, int]` — one query, `group_by(source_type)` with the same commerce join.
- `list_by_comercio(id_comercio, modelo) -> list[ProductoPresentacionEmbedding]` — thin wrapper over the existing `ProductoPresentacionEmbeddingRepository.list_by_comercio(...)` for the per-presentation breakdown.

All three reads go through the existing parent-chain joins used by `list_by_comercio`. Status values come from the `EmbeddingStatus` enum. No new SQLAlchemy mapping is introduced.

Alternatives considered:

- Add the aggregations to the existing `ProductoPresentacionEmbeddingRepository`. Rejected: that repository stays read-write and intentionally narrow per the 4.6 contract; mixing status aggregations with `update_document` violates the 4.6 boundary.
- Return raw SQLAlchemy rows from the router. Rejected: routers do not own SQLAlchemy (boundary test enforces this).

### 5. Transaction boundary: `Depends(get_session)` owns the session lifetime; the router owns only `commit` / `rollback`

The router uses the project's standard FastAPI session dependency (`backend.dependencies.get_session`, which is a `_SessionLocal()` wrapped in a `try / yield / finally: session.close()` generator). The router module imports `Annotated, Any` from `typing` and `Depends` from `fastapi`; it does NOT import `sqlalchemy` solely for the session type annotation. The route handler declares

```python
def post_reindex(
    comercio_id: int,
    payload: ProductEmbeddingReindexRequest,
    session: Annotated[Any, Depends(get_session)],
) -> ProductEmbeddingReindexResponse:
```

and inside the body uses a single `try / except` (no `finally` is needed for closing because the generator owns it):

```python
try:
    result = service.run_reindex(...)
    if not payload.dry_run:
        session.commit()
except Exception:
    session.rollback()
    raise
return response
```

`backend.dependencies.get_session` is the sole owner of `session.close()` — it runs in the generator's `finally` once the request finishes, regardless of whether `commit` / `rollback` was called. The router MUST NOT call `session.close()`. Tests override `get_session` through `app.dependency_overrides[get_session]` to inject a `MagicMock(name="DatabaseSession")` and assert the lifecycle (`commit` once after a completed real run, no `commit` on `dry_run`, one `rollback` on an unhandled exception, `close` never called by the router, `close` is the dependency generator's responsibility).

For the GET status endpoint the router uses the same `Depends(get_session)` dependency. Status performs no `commit` / `rollback` unless an unexpected database error escapes, in which case the route relies on FastAPI's default `500` handling and the `get_session` generator's `finally` to close the session.

Alternatives considered:

- Open `_SessionLocal()` directly inside a custom `try / except / finally` and re-implement the generator inside the router. Rejected: duplicates the closing path; reintroduces the contradiction with the rest of the project's FastAPI routers (every other router goes through `Depends(get_session)`).
- Implement middleware. Rejected: the boundary is route-scoped (only the admin endpoints need the explicit handling today; Subphase 4.6 already commit-on-success semantics are owned by the CLI).

### 6. Response DTOs: explicit Pydantic shapes, vector excluded

`backend/schemas/product_embedding_admin.py` defines:

- `ProductEmbeddingReindexRequest` — optional `producto_id`, `producto_presentacion_id`, `force`, `dry_run`, `batch_size`.
- `ProductEmbeddingReindexResponse` — `comercio_id`, `producto_id`, `producto_presentacion_id`, `dry_run`, `force`, plus `EmbeddingCounters(created, updated, unchanged, stale, inactive, failed)`, plus a list of `PerPresentationOutcome(id_producto_presentacion, status, reason, created, updated, unchanged, stale, inactive, failed)`. No vectors, no exception details, no `last_error` echo (the 4.6 service surfaces reason only for indexer-side failures such as `InvalidProductEmbeddingDocument`).
- `ProductEmbeddingStatusResponse` — `comercio_id`, `embedding_model`, `embedding_dimension`, `total`, `EmbeddingStatusCounts(pending, ready, failed, stale, inactive)`, `active`, `with_last_error`, `EmbeddingSourceTypeCounts(canonical, description, alias, combined)`. No vectors, no `last_error` echo.

The schemas module exports the request / response shapes plus the embedded counter shapes via `__all__`, matching every other `backend/schemas/*.py` module.

Alternatives considered:

- Re-use the existing `SeedingResult` dataclass for the reindex response. Rejected: dataclasses do not produce OpenAPI schemas and they would expose internal fields like `outcomes` directly.
- Return raw `dict`s. Rejected: every other router in the project serializes through Pydantic, so this would break the convention.

### 7. Error mapping: narrow set of HTTP codes

Exception → HTTP code mapping at the router:

- `LocalAdminEndpointsDisabled` → never raised (the gate is a `404` short-circuit before any service call).
- `ComercioNotFound` → `404`.
- `InvalidProductEmbeddingAdminScope` (a new exception wrapping ONLY "invalid producto_id / producto_presentacion_id for the given comercio_id" — it MUST NOT wrap the batch_size case) → `400`.
- `InvalidBatchSize` (a separate exception, raised by the service when `batch_size` is `<= 0`; the Pydantic request schema does NOT validate `batch_size`) → `400`.
- `HTTPException` from `int()` parsing / negative ids on the URL path → `400` (FastAPI default).
- Recoverable embedding failures (raised as the result's `failed > 0`) → `200` with counters. Never `500`.
- Unhandled persistence or infrastructure error → `500` (default FastAPI behavior; the `try / except` wrapper logs nothing user-facing, the `rollback()` runs, and the body stays the default `Internal Server Error`).

### 8. Testing strategy: `TestClient` against fake indexing dependencies

The endpoint tests use FastAPI's `TestClient` with a thin test app (`app = FastAPI(); app.include_router(...router)`) and inject the SQLAlchemy session through `app.dependency_overrides[get_session] = override_get_session`. `override_get_session` is a regular function (no `yield`) that returns a `MagicMock(name="DatabaseSession")` so the test can assert `mock.commit`, `mock.rollback`, and `mock.close` call counts directly. A separate small unit test exercises the original `backend.dependencies.get_session` generator to confirm the generator's `finally` calls `session.close()`. The service's `OllamaEmbeddingClient` / `indexer` / `seeder` are replaced through constructor injection (the embedding client transport is faked through `transport=`; the indexer and seeder are constructed with fakes). No real Ollama call. No real `_SessionLocal`. The status tests instantiate the new repository against `supernova_test` (the same DB the 4.6 indexer tests use).

The session lifecycle assertions cover:

- dry-run → `commit` NOT called, `rollback` NOT called, `close` NOT called from the route.
- successful real run → `commit` called exactly once, `rollback` NOT called, `close` NOT called from the route.
- unhandled exception → `rollback` called exactly once, `commit` NOT called, the exception propagates so FastAPI returns `500`, `close` NOT called from the route.
- the original `get_session` generator closes the session in its `finally` (one assertion in a separate unit test).

### 9. Module boundary enforcement: `grep`-style source assertions

A dedicated `backend/tests/test_admin_product_embeddings_module_boundaries.py` asserts:

- The router module does NOT import `sqlalchemy`, does NOT import `backend.llm` / `backend.repositories` / `backend.embeddings` / `backend.scripts`, does NOT call `db.close()`, and only calls `db.commit()` / `db.rollback()` inside its own `try / except` block (no `finally: db.close()`). It does NOT import `requests`, `asyncio`, `async def`, `await `, `time.sleep`, `retry`, `backoff`, `print(`, `logger.`, `logging.`. It only calls the admin service.
- The admin service module does NOT import `fastapi`, `sqlalchemy`, or `requests`. It does NOT call `commit`, `rollback`, `close`, or `begin`. It does NOT contain raw SQLAlchemy queries. It DOES instantiate `OllamaEmbeddingClient(effective_settings)` through the existing constructor `(settings, transport=None, clock=None)` (the constructor signature is NOT extended). It imports `dataclasses` only for the `dataclasses.replace(settings, embedding_batch_size=...)` override on the frozen `Settings`.
- The status repository module does NOT import HTTP, `fastapi`, `requests`, the embedding client, the indexer, the seeder, the admin service, or any router. It does NOT call `commit`, `rollback`, `close`, `begin`.
- The schemas module exposes exactly the seven exported names through `__all__`.

These mirror the boundary tests in `test_incoming_messages_endpoint.py::IncomingMessagesModuleBoundaryTest` and `test_seed_product_presentation_embeddings_cli.py`.

## Risks / Trade-offs

- [Risk] Returning `404` for disabled local-admin endpoints hides the configuration knob from operators. → Mitigation: the disabled-flag check participates in OpenAPI metadata; the 4.7 status log ships with a "gate" note in `enable_local_admin_endpoints` docstring so operators can diagnose a missing route without reading source.
- [Risk] Duplicate per-presentation outcomes in the reindex response would multiply payload size on large catalogs. → Mitigation: response is built from `SeedingResult.outcomes` without re-fetching any rows; the field is documented as a list and the test asserts the structural shape, not its size.
- [Risk] The new `ENABLE_LOCAL_ADMIN_ENDPOINTS` setting is read once at app startup via `load_settings()`. A future operator that toggles it at runtime would not see the change. → Mitigation: the existing `load_settings()` contract is "load once at startup"; this is consistent with every other boolean env var in the project (`LLM_LOG_CONTENT`, `ENABLE_*` family planned for later phases). Documented in the schema docstring.
- [Risk] An unhandled exception during dry-run still bubbles through to FastAPI's `500` even though the route never called `commit`. → Mitigation: the nine numbered test cases from `openspec/specs/project.md` §4.7 do not require a non-500 on unhandled exceptions during dry-run; only the persistence-path assumption (no commit, `rollback` once, no `close` in the route) is asserted. The `get_session` generator's `finally` still closes the session after the `500`.
- [Risk] The admin service instantiates `OllamaEmbeddingClient`; if a future change introduces a side effect inside the constructor (e.g., a network warm-up call) the HTTP path would block on first request. → Mitigation: the existing constructor `(settings, transport=None, clock=None)` is unchanged and the Subphase 4.4 / 4.6 tests assert it does no I/O; the constructor is exercised only with a fake `transport` in tests so a regression would surface in the boundary tests rather than as a runtime hang.
- [Risk] Status endpoint currently performs no `commit` / `rollback` on the happy path; if a future change adds a write (e.g., to record a read-timestamp) the boundary test would not catch a missing `commit`. → Mitigation: the boundary test asserts `db.commit.assert_not_called()` on the GET status happy path; future writes must update the boundary test together with the new commit.

## Migration Plan

- No DB migration. The 4.6 model, migration, partial unique indexes, and CHECK constraints already expose everything the new endpoints read or write.
- Deployment steps:
  1. Pull the 4.7 branch.
  2. Restart the FastAPI app (`uvicorn backend.main:app --reload`) so the new router is registered.
  3. (Optional) set `ENABLE_LOCAL_ADMIN_ENDPOINTS=true` in the local `.env` and restart.
  4. Confirm `curl -i -X POST http://localhost:8000/admin/comercios/1/product-embeddings/reindex -H 'Content-Type: application/json' -d '{"dry_run": true}'` returns `200` (or `404` when the flag is unset).
- Rollback: revert the commit; no data migration to undo. The `Settings.enable_local_admin_endpoints` field is additive — removing it is safe as long as no other code references it.
- Backward compatibility: the new field defaults to `False`, every existing behavior of the 4.6 CLI, the indexer / seeder / service / repository / model, and every existing FastAPI route is unchanged.

## Open Questions

- Should the status response include the per-`embedding_status` counts broken down by `source_type` (e.g., `canonical → ready`, `alias → failed`) once the catalog grows? The current design reports only the aggregated counts because the four-bucket split is enough for operator triage today and any finer breakdown can be added in a later subphase without touching the persistence shape. Decision: aggregate only. Document in the spec's response example.
- Should the reindex response ever echo the per-presentation `reason` field? The 4.6 indexer surfaces a reason only for indexer-side failures (`InvalidProductEmbeddingDocument`); recoverable embedding failures never carry a reason. Decision: include `reason` as `Optional[str]` so operator triage works for indexer-side failures and stays empty for embedding-side failures.
