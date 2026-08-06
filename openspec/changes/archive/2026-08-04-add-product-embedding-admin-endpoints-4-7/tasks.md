## 1. Settings: enable the local-admin gate

- [x] 1.1 In `backend/config/settings.py`, add `enable_local_admin_endpoints: bool = False` to the frozen `Settings` dataclass (placed after the existing `embedding_batch_size` field).
- [x] 1.2 In `load_settings()`, populate the field through `_bool_env("ENABLE_LOCAL_ADMIN_ENDPOINTS", False)`. No new helper needed; reuse the existing `_bool_env` validator.
- [x] 1.3 Update the module's `__all__` if it explicitly enumerates the settings names (it currently exports only the public dataclass and helpers; no change needed unless a stricter list emerges later).

## 2. Exception surface for the admin endpoints

- [x] 2.1 In `backend/services/exceptions.py`, add `LocalAdminEndpointsDisabled(Exception)`, `InvalidProductEmbeddingAdminScope(ValueError)`, and `InvalidBatchSize(ValueError)`. Keep the existing `EmbeddingNotFound` / `InvalidEmbedding` aliases.
- [x] 2.2 Document that the disabled-endpoints case is not raised as an exception — it is a `404` short-circuit at the router layer — that `InvalidProductEmbeddingAdminScope` covers ONLY "invalid producto_id / producto_presentacion_id for the given comercio_id" (mapped to `400` by the router), and that non-positive `batch_size` is raised separately as `InvalidBatchSize` (also mapped to `400` by the router). The two exceptions are independent — `InvalidProductEmbeddingAdminScope` MUST NOT wrap the `batch_size` case.

## 3. Status repository (reads only)

- [x] 3.1 Create `backend/repositories/producto_presentacion_embedding_status_repository.py` exporting `EmbeddingStatusCounts` (frozen dataclass with `pending`, `ready`, `failed`, `stale`, `inactive`, `total`, `active`, `with_last_error`) and `EmbeddingSourceTypeCounts` (frozen dataclass with `canonical`, `description`, `alias`, `combined`).
- [x] 3.2 Add `ProductoPresentacionEmbeddingStatusRepository(session)` with `count_by_comercio(id_comercio, modelo) -> EmbeddingStatusCounts`, `count_by_source_type(id_comercio, modelo) -> EmbeddingSourceTypeCounts`, and `list_by_comercio(id_comercio, modelo) -> list[ProductoPresentacionEmbedding]`.
- [x] 3.3 Implement `count_by_comercio` with a single SQL `func.count()` / `func.count().filter(...)` aggregation that joins `ProductoPresentacionEmbedding` × `ProductoPresentacion` × `Producto` × `CategoriaProducto` and filters on `CategoriaProducto.id_comercio == id_comercio` and `modelo`. Run the count as one query.
- [x] 3.4 Implement `count_by_source_type` with a single SQL `group_by(source_type)` aggregation that uses the same parent-chain join. Return zero for any source_type that has no rows.
- [x] 3.5 Implement `list_by_comercio` as a thin wrapper that returns the underlying `ProductoPresentacionEmbedding` rows through the existing 4.6 parent-chain join. Re-use the 4.6 `joinedload` to avoid N+1 if needed.
- [x] 3.6 The repository MUST NOT import HTTP, FastAPI, the embedding client, the indexer, or the seeder. The repository MUST NOT call `commit`, `rollback`, `close`, or `begin`.

## 4. Admin service (owns the embedding client / indexer / seeder; no SQLAlchemy, no commit)

- [x] 4.1 Create `backend/services/producto_presentacion_embedding_admin_service.py` exporting `ProductoPresentacionEmbeddingAdminService(session)`. The service is the single owner of `OllamaEmbeddingClient`, `ProductoPresentacionEmbeddingIndexer`, and `ProductoPresentacionEmbeddingSeeder` for the HTTP path. Prefer constructor / factory injection: when present, the constructor accepts `embedding_client`, `indexer`, and `seeder` overrides; when absent, the service instantiates them per request from `OllamaEmbeddingClient(effective_settings)` (the existing `(settings, transport=None, clock=None)` constructor — NOT extended), `ProductoPresentacionEmbeddingIndexer(...)`, and `ProductoPresentacionEmbeddingSeeder(...)`. Tests substitute fakes through the constructor to avoid a real Ollama call.
- [x] 4.2 Add `run_reindex(*, id_comercio, id_producto=None, id_producto_presentacion=None, force=False, dry_run=False, batch_size=None) -> SeedingResult`:
  - Validate the comercio through `ComercioService.get_by_id(id_comercio)` (raises `ComercioNotFound`).
  - When `id_producto` or `id_producto_presentacion` is supplied, validate against the parent-chain projection to ensure it belongs to the comercio (raises `InvalidProductEmbeddingAdminScope` when not).
  - When `batch_size` is supplied, validate it is a positive integer (raises `InvalidBatchSize`).
  - Build the effective `Settings` through `dataclasses.replace(base_settings, embedding_batch_size=batch_size)` when `batch_size` is not None.
  - Build the `OllamaEmbeddingClient` (constructor stays `(settings, transport=None, clock=None)`; do NOT modify), the `ProductoPresentacionEmbeddingIndexer`, and the `ProductoPresentacionEmbeddingSeeder` (per-request or via constructor injection). Call `seeder.run(session, id_comercio=id_comercio, id_producto=id_producto, id_producto_presentacion=id_producto_presentacion, force=force, dry_run=dry_run)` and return the `SeedingResult`.
  - Never call `commit`, `rollback`, `close`, or `begin`. Never call `flush()`.
- [x] 4.3 Add `get_status(*, id_comercio) -> tuple[EmbeddingStatusCounts, EmbeddingSourceTypeCounts, list[ProductoPresentacionEmbedding]]`:
  - Validate the comercio through `ComercioService.get_by_id(id_comercio)` (raises `ComercioNotFound`).
  - Read `settings.embedding_model` (call `load_settings()`).
  - Delegate to the new status repository: `repository.count_by_comercio(id_comercio, embedding_model)`, `repository.count_by_source_type(id_comercio, embedding_model)`, `repository.list_by_comercio(id_comercio, embedding_model)`.
  - Return the three values so the router can build the response DTO.
  - Never call `commit`, `rollback`, `close`, or `begin`.
- [x] 4.4 The admin service module MUST NOT import `sqlalchemy`, `fastapi`, or `requests`. It MUST NOT contain raw SQLAlchemy queries (those live in the repositories). It MUST NOT call `commit`, `rollback`, `close`, or `begin`. It DOES instantiate or accept the `OllamaEmbeddingClient`, `ProductoPresentacionEmbeddingIndexer`, and `ProductoPresentacionEmbeddingSeeder` — the constructor signature of `OllamaEmbeddingClient` remains `(settings, transport=None, clock=None)` and is NOT extended. Constructor / factory injection is preferred but not mandated for every object — `dataclasses.replace(...)` is the only required use of `dataclasses`.

## 5. Pydantic schemas (request / response shape)

- [x] 5.1 Create `backend/schemas/product_embedding_admin.py` exporting `ProductEmbeddingReindexRequest`, `ProductEmbeddingReindexResponse`, `ProductEmbeddingStatusResponse`, `ProductEmbeddingStatusCounts`, `ProductEmbeddingSourceTypeCounts`, `ProductEmbeddingCounters`, and `PerPresentationOutcome` through `__all__`.
- [x] 5.2 `ProductEmbeddingReindexRequest` carries optional `producto_id`, `producto_presentacion_id`, `force`, `dry_run`, `batch_size` as plain types — the schema does NOT validate `batch_size` (no field validator, no `ValueError`). The schema accepts whatever JSON the client sends for `batch_size` and lets it flow through to the service; the service raises `InvalidBatchSize` for non-positive values, which the router maps to `400`. This avoids the `pydantic.ValidationError` → `422` path that a Pydantic field validator would produce.
- [x] 5.3 `ProductEmbeddingReindexResponse` carries `comercio_id`, `producto_id`, `producto_presentacion_id`, `force`, `dry_run`, `counters: ProductEmbeddingCounters`, `outcomes: list[PerPresentationOutcome]`. No vectors, no source text, no last error echo.
- [x] 5.4 `ProductEmbeddingStatusResponse` carries `comercio_id`, `embedding_model`, `embedding_dimension`, `total`, `counts: ProductEmbeddingStatusCounts`, `active`, `with_last_error`, `source_type_counts: ProductEmbeddingSourceTypeCounts`. No vectors, no source text, no last error echo.

## 6. Router and transaction boundary

- [x] 6.1 Create `backend/routers/admin_product_embeddings.py` exposing `APIRouter(tags=["admin-product-embeddings"])` with two routes:
  - `POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
  - `GET /admin/comercios/{comercio_id}/product-embeddings/status`
- [x] 6.2 Define a small `_gate_enabled() -> bool` dependency that reads `Settings.enable_local_admin_endpoints` from `load_settings()`. Add `Annotated[..., Depends(_gate_enabled)]` to every route; the gate is the FIRST line of the route body so a `404` is returned before any service work.
- [x] 6.3 Implement the POST handler:
  - Read the JSON body through the `ProductEmbeddingReindexRequest` Pydantic model.
  - Declare the session through `Depends(get_session)` — the route handler signature uses `session: Annotated[Any, Depends(get_session)]` (the router imports `Annotated, Any` from `typing` instead of `Session` from `sqlalchemy`, so importing `sqlalchemy` is NOT required solely for this type annotation). The route handler does NOT import `_SessionLocal` and does NOT call `session.close()`.
  - Inside the route body, wrap the service call in a single `try / except` (no `finally: session.close()`):
    - `try: result = service.run_reindex(...); if not payload.dry_run: session.commit()`,
    - `except Exception: session.rollback(); raise`.
  - Delegate to `ProductoPresentacionEmbeddingAdminService.run_reindex(...)`.
  - Map exceptions: `ComercioNotFound` → `404`; `InvalidProductEmbeddingAdminScope` → `400`; `InvalidBatchSize` → `400`; `pydantic.ValidationError` → FastAPI default `422`; everything else → default `500`.
  - Build the response through `ProductEmbeddingReindexResponse.model_validate(...)`.
- [x] 6.4 Implement the GET handler:
  - Declare the session through `Depends(get_session)` (same form as the POST handler). The route handler does NOT import `_SessionLocal` and does NOT call `session.close()`.
  - On the happy path, perform no `session.commit()` and no `session.rollback()`; the `get_session` generator closes the session in its `finally` once the response is sent.
  - Delegate to `ProductoPresentacionEmbeddingAdminService.get_status(...)`.
  - Build the response through `ProductEmbeddingStatusResponse.model_validate(...)`. Map `ComercioNotFound` → `404`.
- [x] 6.5 The router module MUST NOT import SQLAlchemy. It MUST NOT import `backend.llm` / `backend.repositories` / `backend.embeddings` / `backend.scripts`. It MUST NOT call `db.close()` anywhere. The only calls into business logic go through the admin service.
- [x] 6.6 Register the router in `backend/main.py` with `app.include_router(admin_product_embeddings.router)` immediately after the embedding-adjacent routers (after `incoming_messages.router` or wherever the ordering minimizes churn).

## 7. Endpoint tests (focused, fastapi TestClient)

- [x] 7.1 Create `backend/tests/test_admin_product_embeddings_endpoints.py` (FastAPI `TestClient`, fast, fake indexing dependencies, no real Ollama).
- [x] 7.2 Build the test app the same way `test_incoming_messages_endpoint.py` does: `app = FastAPI(); app.include_router(router_module.router); app.dependency_overrides[get_session] = override_get_session` so a `MagicMock(name="DatabaseSession")` is injected. `override_get_session` is a plain function returning the mock (NOT a generator) so call counts on the mock reflect the route handler's actions only.
- [x] 7.3 Cover the nine numbered cases from `openspec/specs/project.md` §4.7:
  - `(1)` endpoints return `404` when the gate is disabled; assert no service call.
  - `(2)` status endpoint is commerce-isolated and returns correct status counters (status counts, active count, `with_last_error` count, source-type counts, totals).
  - `(3)` status response never exposes vectors (assert the response JSON has no key resembling `vector` / `source_text` / `normalized_text` / `content_hash` / `last_error` / `fecha_alta` / `fecha_ultima_modificacion`).
  - `(4)` reindex endpoint passes the commerce scope and accepted options to the existing 4.6 service (use a fake admin service inside the test that records the call).
  - `(5)` dry-run performs no commit (assert `db.commit.assert_not_called()`).
  - `(6)` completed real run commits once (assert `db.commit.assert_called_once()`).
  - `(7)` unhandled failure rolls back (assert `db.rollback.assert_called_once()`, response status `500`).
  - `(8)` missing comercio returns `404`; invalid scope returns `400`; non-positive batch size returns `400`.
  - `(9)` recoverable embedding failures return counters with `failed > 0` without leaking internal details (assert response status `200`, `failed` counter populated, no exception trace in the body).
- [x] 7.4 Cover the FastAPI session lifetime (assertions on the injected mock + the original generator):
  - across the nine focused cases the mock's `db.close.assert_not_called()` holds (the route handler must NEVER call `close`);
  - the original `backend.dependencies.get_session` generator closes its session in `finally` (separate small unit test that drives the generator directly and asserts the real `_SessionLocal` session receives a `close()` call);
  - the GET status happy path asserts `db.commit.assert_not_called()` and `db.rollback.assert_not_called()`.

## 8. Module boundary tests

- [x] 8.1 Create `backend/tests/test_admin_product_embeddings_module_boundaries.py` mirroring `test_incoming_messages_endpoint.py::IncomingMessagesModuleBoundaryTest`.
- [x] 8.2 Assert the router source:
  - does NOT import `sqlalchemy`, `backend.llm`, `backend.repositories`, `backend.embeddings`, `backend.scripts`;
  - does NOT call `db.close()` anywhere (the `get_session` generator is the sole `close()` owner); `db.commit` / `db.rollback` MAY appear inside the route handler's `try / except` block;
  - does NOT import `_SessionLocal`;
  - does NOT import `requests`, `asyncio`, `async def`, `await `, `time.sleep`, `retry`, `backoff`, `print(`, `logger.`, `logging.`;
  - exposes only the two route handlers through `APIRouter.post` / `APIRouter.get`.
- [x] 8.3 Assert the admin service source:
  - does NOT import `sqlalchemy`, `fastapi`, `requests`;
  - does NOT call `commit`, `rollback`, `close`, `begin`;
  - DOES import / instantiate / accept `OllamaEmbeddingClient`, `ProductoPresentacionEmbeddingIndexer`, and `ProductoPresentacionEmbeddingSeeder` (those three are required — instantiation or constructor / factory injection are both acceptable); the `OllamaEmbeddingClient` constructor signature remains `(settings, transport=None, clock=None)` and the service does NOT extend it;
  - imports `dataclasses` only for the `dataclasses.replace(...)` Settings override.
- [x] 8.4 Assert the status repository source:
  - does NOT import HTTP, `fastapi`, `requests`, the embedding client, the indexer, the seeder, the admin service, or any router;
  - does NOT call `commit`, `rollback`, `close`, `begin`.
- [x] 8.5 Assert the schemas module `__all__` is exactly the list exported in task 5.1.

## 9. Regression coverage (minimum indispensable)

- [x] 9.1 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_producto_presentacion_embedding_indexer.py -q` to confirm Subphase 4.6 indexer still passes.
- [x] 9.2 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_seed_product_presentation_embeddings_cli.py -q` to confirm the Subphase 4.6 CLI runner still passes.
- [x] 9.3 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_producto_presentacion_embedding_migration.py backend/tests/test_producto_presentacion_embedding_model.py backend/tests/test_producto_presentacion_embedding_integration.py -q` to confirm the Subphase 4.6 persistence surface still passes.
- [x] 9.4 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_ollama_embedding_client.py backend/tests/test_product_embedding_document_builder.py -q` to confirm Subphases 4.4 / 4.5 embedding client and pure builder still pass.
- [x] 9.5 Do NOT require the full `api_smoke.py` run or unrelated fuzzy-recognizer suites unless a focused test reveals a regression there.

## 10. Static checks

- [x] 10.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0.
- [x] 10.2 `PYTHONPATH=. venv/bin/python -m ruff check backend/config/settings.py backend/services/producto_presentacion_embedding_admin_service.py backend/services/exceptions.py backend/repositories/producto_presentacion_embedding_status_repository.py backend/schemas/product_embedding_admin.py backend/routers/admin_product_embeddings.py backend/main.py backend/tests/test_admin_product_embeddings_endpoints.py backend/tests/test_admin_product_embeddings_module_boundaries.py` reports no new failures.
- [x] 10.3 `PYTHONPATH=. venv/bin/python -m mypy backend/config/settings.py backend/services/producto_presentacion_embedding_admin_service.py backend/services/exceptions.py backend/repositories/producto_presentacion_embedding_status_repository.py backend/schemas/product_embedding_admin.py backend/routers/admin_product_embeddings.py backend/main.py` reports no new errors.
- [x] 10.4 Verify the no-commit / no-rollback / no-close / no-begin rule on the new modules: `grep -nE "session\.(commit|rollback|close|begin)\(" backend/services/producto_presentacion_embedding_admin_service.py backend/repositories/producto_presentacion_embedding_status_repository.py` returns no matches. The router MAY call `session.commit()` and `session.rollback()` inside its `try / except` block; verify `grep -nE "session\.close\(" backend/routers/admin_product_embeddings.py` returns no matches (the `get_session` generator is the sole close owner).
- [x] 10.5 Verify the schemas module exposes exactly `__all__ = ["ProductEmbeddingReindexRequest", "ProductEmbeddingReindexResponse", "ProductEmbeddingStatusResponse", "ProductEmbeddingStatusCounts", "ProductEmbeddingSourceTypeCounts", "ProductEmbeddingCounters", "PerPresentationOutcome"]` and nothing else.
- [x] 10.6 `openspec validate add-product-embedding-admin-endpoints-4-7 --strict` is valid; the change remains active and unsynchronized.

## 11. Manual verification

- [x] 11.1 Restart the FastAPI app with `ENABLE_LOCAL_ADMIN_ENDPOINTS=false` (the default). `curl -i http://localhost:8000/admin/comercios/1/product-embeddings/status` and the equivalent POST return `404`. Confirm the OpenAPI tag `admin-product-embeddings` documents the disabled state.
- [x] 11.2 Restart the FastAPI app with `ENABLE_LOCAL_ADMIN_ENDPOINTS=true`. `curl -i -X POST http://localhost:8000/admin/comercios/1/product-embeddings/reindex -H 'Content-Type: application/json' -d '{"dry_run": true}'` returns `200` with the six counters. `curl -i http://localhost:8000/admin/comercios/1/product-embeddings/status` returns `200` with the status summary.
- [x] 11.3 Spot-check `psql supernova -c "SELECT id_producto_presentacion, source_type, embedding_status, activo FROM producto_presentacion_embeddings WHERE embedding_status='ready' ORDER BY id_producto_presentacion LIMIT 5;"` confirms the persisted state matches the status response (no vectors exposed by the endpoint).
- [x] 11.4 Spot-check the response payload for the status endpoint: `curl -s http://localhost:8000/admin/comercios/1/product-embeddings/status | python -c "import json,sys; d=json.load(sys.stdin); assert 'vector' not in str(d); assert 'source_text' not in str(d); assert 'normalized_text' not in str(d); assert 'content_hash' not in str(d); print('ok')"` to confirm no sensitive fields leak.

## 12. Reporting

- [x] 12.1 Report the new `ENABLE_LOCAL_ADMIN_ENDPOINTS` setting (default `false`, env var, validation, read-only usage), the new `LocalAdminEndpointsDisabled` / `InvalidProductEmbeddingAdminScope` / `InvalidBatchSize` exception surface, the new `ProductoPresentacionEmbeddingStatusRepository` (per-status and per-source-type aggregations over the existing 4.6 model), the new `ProductoPresentacionEmbeddingAdminService` (commerce validation + commerce-scoped projection validation + batch-size validation + `dataclasses.replace` for the `Settings.embedding_batch_size` override + owns the `OllamaEmbeddingClient` / `ProductoPresentacionEmbeddingIndexer` / `ProductoPresentacionEmbeddingSeeder` triple through constructor / factory injection), the new Pydantic request / response schemas, the new `backend/routers/admin_product_embeddings.py` (route handlers, the gate dependency, `Depends(get_session)` for the FastAPI session lifetime, the inner `try / except` transaction boundary that commits / rolls back and never calls `close()`, the `get_session` generator as the sole session-close owner, the disabled-endpoint `404` short-circuit, the exception → HTTP mapping), the new endpoint tests (nine focused cases + the FastAPI session lifetime assertions through `app.dependency_overrides[get_session]` and the original `get_session` generator), the new boundary tests (no SQLAlchemy in router; no `db.close()` in router; no commit / rollback / close / begin in service or repository; the OllamaEmbeddingClient constructor unchanged; constructor / factory injection preserves testability), the registered router in `backend/main.py`, the static checks (compileall, ruff, mypy, openspec validate), the manual verification, files changed, tests executed and their results, and confirm that no model / migration / embedding-client / pure-builder / recognizer module was changed in behavior, the 4.6 CLI is untouched, and the OpenSpec change remains active.
