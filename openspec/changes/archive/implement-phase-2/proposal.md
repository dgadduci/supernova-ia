## Why

Phase 1 closed with the SQLAlchemy model layer, the Alembic initial migration, and the seed scripts. Phase 2 introduces the FastAPI API layer incrementally, one resource per subphase, with the minimum infrastructure (FastAPI app, /health, session dependency) delivered alongside the first vertical slice. Subphase 2.1 is the first of those subphases, anchored on the existing `Comercio` model.

## What Changes

- Add the FastAPI infrastructure: `backend/main.py` (app factory + router registration + `/health`), `backend/dependencies.py` (one SQLAlchemy session per request via `yield`, closed after the request).
- Add the commerce vertical slice: `ComercioCreate` and `ComercioResponse` Pydantic schemas, a `ComercioRepository`, a `ComercioService` with domain exceptions, and a `comercios` router exposing `GET /comercios`, `GET /comercios/{comercio_id}`, and `POST /comercios`.
- Add minimum endpoint integration tests against `supernova_test`.
- Do **not** modify `Comercio` or `EstadoComercio` models, do **not** generate a new Alembic migration, do **not** implement update/delete/pagination/auth/nested-resource endpoints.

## Capabilities

### New Capabilities

- `fastapi-infrastructure`: Sync FastAPI app bootstrap (Uvicorn-compatible), `/health` endpoint returning `{"status": "ok"}`, and the per-request SQLAlchemy session dependency. No business logic.
- `comercios-api`: HTTP layer over the existing `Comercio` model — `GET /comercios` (list, ordered by id), `GET /comercios/{comercio_id}` (one, 404 if missing), `POST /comercios` (create with whitespace trim, empty-rejection, estado existence check, whatsapp and slug uniqueness; 201 on success, 404 on missing estado, 409 on duplicate whatsapp/slug; transaction rolled back on DB error). No metodos_entrega/medios_pago associations are created as part of this subphase.

### Modified Capabilities

_None._ No existing spec requirements change.

## Impact

- **New files under `backend/`**: `main.py`, `dependencies.py`, `routers/comercios.py`, `schemas/comercio.py`, `repositories/comercio_repository.py`, `services/comercio_service.py`, `services/exceptions.py`. `__init__.py` only where required by existing package structure.
- **New test module(s) under `backend/tests/`** (or wherever existing tests live — TBD by repo convention): integration tests against `supernova_test`.
- **Untouched**: all 11 SQLAlchemy models, the Alembic config, the seed scripts, both `supernova` and `supernova_test` data.
- **Out of scope**: any endpoint beyond the three listed, the second resource, Alembic migrations for API metadata, authentication, pagination, response schemas for metodos_entrega/medios_pago.
