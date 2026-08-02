## 1. Domain exceptions

- [x] 1.1 Extend `backend/services/exceptions.py` with `EstadoComercioNotFound`, `EstadoComercioInUse`, and `DuplicateEstado`

## 2. EstadoComercio schemas

- [x] 2.1 Create `backend/schemas/estado_comercio.py` defining `EstadoComercioCreate` (single required `estado` text field; rejects empty after whitespace trim) and `EstadoComercioResponse` (`id` + `estado`, with `from_attributes=True`)

## 3. EstadoComercio repository

- [x] 3.1 Create `backend/repositories/estado_comercio_repository.py` with `list_all`, `get_by_id`, `get_by_estado`, `create`, and `estado_in_use`
- [x] 3.2 Confirm the repository uses SQLAlchemy ORM or `select()` statements only; no `commit()` or `rollback()` calls

## 4. EstadoComercio service

- [x] 4.1 Create `backend/services/estado_comercio_service.py` with `list_all`, `get_by_id`, and `create`. `create` must trim whitespace on `estado`, reject empty values, check duplicate `estado` via the repository, raise `DuplicateEstado` on collision, commit on success, roll back on any DB error

## 5. EstadoComercio router

- [x] 5.1 Create `backend/routers/estados_comercios.py` with `GET /estados-comercio`, `GET /estados-comercio/{estado_comercio_id}`, and `POST /estados-comercio`. Each endpoint declares the session dependency and the service dependency
- [x] 5.2 Register the router in `backend/main.py`

## 6. Minimum integration tests

- [x] 6.1 Extend `backend/tests/api_smoke.py` with the seven new scenarios: GET list returns existing rows ordered by id; GET one returns 404 for missing id; POST creates a row and returns 201; POST returns 409 on duplicate `estado`; POST trims whitespace; POST rejects empty `estado`; POST rejects `id` in body
- [x] 6.2 Run the extended integration test suite against `supernova_test` and confirm all tests pass

## 7. project.md update

- [x] 7.1 Replace the `### Subphase 2.2 — TBD` placeholder in `openspec/specs/project.md` with the implemented subphase entry, following the `### Subphase Template` shape but condensed per `completed-subphase-context-condensation` (so the entry stays minimal even while active)

## 8. Completion check

- [x] 8.1 Confirm no SQLAlchemy model file was modified by this change
- [x] 8.2 Confirm no Alembic revision was generated (`alembic check` reports "No new upgrade operations detected")
- [x] 8.3 Confirm Phase 2 General Rules, the Subphase 2.1 condensed summary, and the `completed-subphase-context-condensation` spec are all untouched
