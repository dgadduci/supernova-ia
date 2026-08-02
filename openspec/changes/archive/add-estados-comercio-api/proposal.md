## Why

Subphase 2.1 delivered the FastAPI infrastructure and the first vertical slice on `Comercio`. The next catalog root in the dependency chain is `EstadoComercio`: `Comercio.estado_id` FKs to it, so the catalog must be addressable through the same HTTP layer before any per-resource slice that exposes estado references (e.g. nested responses on `Comercio`) can be added.

## What Changes

- Add the `EstadoComercio` vertical slice on top of the infrastructure shipped by Subphase 2.1:
  - `EstadoComercioCreate` and `EstadoComercioResponse` Pydantic schemas.
  - `EstadoComercioRepository` with `list_all`, `get_by_id`, `get_by_estado`, `create`, and `estado_in_use`.
  - `EstadoComercioService` with `list_all`, `get_by_id`, `create`; raises domain exceptions.
  - `estados_comercios` router exposing `GET /estados-comercio`, `GET /estados-comercio/{estado_comercio_id}`, `POST /estados-comercio`.
  - Router, service, and repository wired into `backend/main.py`.
- Add the minimum integration tests against `supernova_test` covering the seven scenarios enumerated in `tasks.md`.
- Replace the `### Subphase 2.2 — TBD` placeholder in `openspec/specs/project.md` with the scope/file/endpoint blocks for this subphase, following the `### Subphase Template` added in the prior change.
- Do **not** modify `EstadoComercio` (model), do **not** generate a new Alembic migration, do **not** introduce update/delete/pagination/auth/nested-resource endpoints, do **not** introduce generic repository or service abstractions.

## Capabilities

### New Capabilities

- `estados-comercio-api`: HTTP layer over the existing `EstadoComercio` model — `GET /estados-comercio` (list ordered by id), `GET /estados-comercio/{estado_comercio_id}` (404 if missing), `POST /estados-comercio` (create with whitespace trim, empty-rejection, duplicate-`estado` 409; 201 on success). No estado references are exposed on `Comercio` responses in this subphase.

### Modified Capabilities

_None._ No existing spec requirements change.

## Impact

- **New files under `backend/`**: `routers/estados_comercios.py`, `schemas/estado_comercio.py`, `repositories/estado_comercio_repository.py`, `services/estado_comercio_service.py`. `__init__.py` only where the existing package structure requires it.
- **Modified files**: `backend/main.py` (register the new router), `backend/services/exceptions.py` (extend with the four new domain exceptions), `backend/tests/api_smoke.py` (or a sibling module — extend with the new scenarios), `openspec/specs/project.md` (replace `Subphase 2.2 — TBD` with the implemented entry).
- **Untouched**: all 11 SQLAlchemy models, the Alembic config, the seed scripts, both `supernova` and `supernova_test` data, the Phase 2 General Rules, the existing Subphase 2.1 condensed summary.
- **Out of scope**: update/delete endpoints; nested-resource endpoints on `Comercio` that surface `estado`; an `estado_in_use` HTTP exposure (the service may use it internally to refuse deletion, but no `DELETE` endpoint is added here); Alembic migrations for API metadata.
