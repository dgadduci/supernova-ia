## Why

Subphases 2.1 (Comercios) and 2.2 (EstadoComercio) shipped the FastAPI infrastructure and the first two vertical slices. `MediosPago` is the next catalog root and the parent of the `comercio_medios_pago` join table (Subphase 1.10); before any per-resource slice exposes payment-method references (nested endpoints on `Comercio`, future POST that wires `comercio_medios_pago`), the catalog itself must be addressable through the same HTTP layer.

## What Changes

- Add the `MediosPago` vertical slice on top of the existing infrastructure:
  - `MediosPagoCreate` and `MediosPagoResponse` Pydantic schemas.
  - `MediosPagoRepository` with `list_all`, `get_by_id`, `get_by_codigo`, `create`.
  - `MediosPagoService` with `list_all`, `get_by_id`, `create`; raises domain exceptions.
  - `medios_pago` router exposing `GET /medios-pago`, `GET /medios-pago/{medio_pago_id}`, `POST /medios-pago`.
  - Router, service, and repository wired into `backend/main.py`.
- Add the minimum integration tests against `supernova_test` covering the scenarios enumerated in `tasks.md`.
- Add a condensed `### Subphase 2.3 — MediosPago` entry in `openspec/specs/project.md`, following the `completed-subphase-context-condensation` rule from day one (no detailed scope/required-files/test-procedures blocks; just decisions, outcomes, constraints, files, future context).
- Do **not** modify `MediosPago` (model), do **not** generate a new Alembic migration, do **not** introduce update/delete/pagination/auth/nested-resource endpoints, do **not** introduce generic repository or service abstractions.

## Capabilities

### New Capabilities

- `medios-pago-api`: HTTP layer over the existing `MediosPago` model — `GET /medios-pago` (list ordered by id), `GET /medios-pago/{medio_pago_id}` (404 if missing), `POST /medios-pago` (create with whitespace trim, empty-rejection, duplicate-`codigo` 409; 201 on success).

### Modified Capabilities

_None._ No existing spec requirements change.

## Impact

- **New files under `backend/`**: `routers/medios_pago.py`, `schemas/medios_pago.py`, `repositories/medios_pago_repository.py`, `services/medios_pago_service.py`. `__init__.py` only where the existing package structure requires it.
- **Modified files**: `backend/main.py` (register the new router), `backend/services/exceptions.py` (extend with the two new domain exceptions), `backend/tests/api_smoke.py` (extend with the new scenarios), `openspec/specs/project.md` (add the condensed Subphase 2.3 entry after 2.2).
- **Untouched**: all 13 SQLAlchemy models, the Alembic config, the seed scripts, both `supernova` and `supernova_test` data, the Phase 2 General Rules, the Subphase 2.1 condensed summary, the Subphase 2.2 condensed summary, the `completed-subphase-context-condensation` spec.
- **Out of scope**: update/delete endpoints; nested-resource endpoints on `Comercio` that surface `medio_pago`; auto-wiring of `comercio_medios_pago` join rows on POST; Alembic migrations for API metadata; `activo` flag mutation endpoints (default True on POST).
