## 1. Schemas and Domain Errors

- [x] 1.1 Create `backend/schemas/presentacion.py` with `PresentacionCreate` and `PresentacionResponse`, forbidding extra fields, excluding `id_comercio`, validating code/description lengths, and rejecting negative supplied `orden`.
- [x] 1.2 Extend `backend/services/exceptions.py` with presentation-not-found, duplicate-code, duplicate-description, and invalid-presentation domain exceptions, reusing the existing commerce-not-found exception.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/presentacion_repository.py` with commerce existence lookup, commerce-scoped listing ordered by `orden` then `id`, presentation lookup by id, case-insensitive scoped code/description lookups, and creation without transaction control or relationship loading.
- [x] 2.2 Create `backend/services/presentacion_service.py` to verify commerce ownership, normalize code, trim and validate text, enforce scoped duplicates, preserve omitted model defaults, create with route-derived commerce IDs, commit success, and roll back failures.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/presentaciones.py` with nested list/create routes and direct presentation retrieval, response models, path-parameter ownership, and domain-to-HTTP exception mapping.
- [x] 3.2 Register the presentation router in `backend/main.py` without changing unrelated routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify presentation creation, normalization, defaults, direct retrieval, and commerce-scoped listing ordered by `orden` then `id`.
- [x] 4.2 Add tests for missing commerce/presentation 404 responses, ownership isolation, body `id_comercio` rejection, and values reused successfully in another commerce.
- [x] 4.3 Add validation and duplicate tests covering empty values, negative `orden`, case-insensitive duplicate code, and case-insensitive duplicate description.
- [x] 4.4 Add or preserve coverage proving presentation creation rolls back on persistence failure and does not create product associations.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.6 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run the presentation integration tests against `supernova_test` and confirm the existing API smoke suite still passes.
- [x] 5.3 Run the project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (scoped checks report only baseline/dependency errors; no new presentation implementation errors).
- [x] 5.4 Confirm `Presentacion` and `Comercio` models, Alembic migrations, product endpoints, product-presentation associations, and update/delete operations remain unchanged.
