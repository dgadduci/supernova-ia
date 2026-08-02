## 1. Domain exceptions

- [x] 1.1 Extend `backend/services/exceptions.py` with `MediosPagoNotFound` and `DuplicateMedioPago`

## 2. MediosPago schemas

- [x] 2.1 Create `backend/schemas/medios_pago.py` defining `MediosPagoCreate` (required `codigo` and `descripcion`; optional `activo` Boolean default `true`; `extra="forbid"`) and `MediosPagoResponse` (full persisted column set with `from_attributes=True`)

## 3. MediosPago repository

- [x] 3.1 Create `backend/repositories/medios_pago_repository.py` with `list_all`, `get_by_id`, `get_by_codigo`, and `create`
- [x] 3.2 Confirm the repository uses SQLAlchemy ORM or `select()` statements only; no `commit()` or `rollback()` calls

## 4. MediosPago service

- [x] 4.1 Create `backend/services/medios_pago_service.py` with `list_all`, `get_by_id`, and `create`. `create` must trim whitespace on `codigo` and `descripcion`, reject empty values, check duplicate `codigo` via the repository, raise `DuplicateMedioPago` on collision, commit on success, roll back on any DB error

## 5. MediosPago router

- [x] 5.1 Create `backend/routers/medios_pago.py` with `GET /medios-pago`, `GET /medios-pago/{medio_pago_id}`, and `POST /medios-pago`. Each endpoint declares the session dependency and the service dependency
- [x] 5.2 Register the router in `backend/main.py`

## 6. Minimum integration tests

- [x] 6.1 Extend `backend/tests/api_smoke.py` with the new scenarios: GET list returns existing rows ordered by id; GET one returns 404 for missing id; POST creates a row and returns 201; POST returns 409 on duplicate `codigo`; POST trims whitespace on `codigo` and `descripcion`; POST rejects empty `codigo`; POST rejects empty `descripcion`; POST rejects `id` in body; POST with omitted `activo` defaults to `true`
- [x] 6.2 Run the extended integration test suite against `supernova_test` and confirm all tests pass

## 7. project.md update

- [x] 7.1 Add a condensed `### Subphase 2.3 — MediosPago` entry in `openspec/specs/project.md` after the Subphase 2.2 entry, following the `completed-subphase-context-condensation` rule from day one (no detailed scope/required-files/test-procedures blocks; only decisions, outcomes, constraints, files, future context)

## 8. Completion check

- [x] 8.1 Confirm no SQLAlchemy model file was modified by this change
- [x] 8.2 Confirm no Alembic revision was generated (`alembic check` reports "No new upgrade operations detected")
- [x] 8.3 Confirm Phase 2 General Rules, the Subphase 2.1 condensed summary, the Subphase 2.2 condensed entry, and the `completed-subphase-context-condensation` spec are all untouched
