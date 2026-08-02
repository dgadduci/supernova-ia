## 1. Response Schemas

- [x] 1.1 Create `backend/schemas/configuracion_comercio.py` with explicit ORM-compatible detail schemas for status, payment catalog/association, delivery catalog/association, and complete commerce configuration.
- [x] 1.2 Ensure the aggregate response includes every commerce scalar field and only the required nested `estado`, `medios_pago`, and `metodos_entrega` fields.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/configuracion_comercio_repository.py` with one commerce-by-ID query that eagerly loads status and both association/catalog branches without product relationships or N+1 behavior.
- [x] 2.2 Preserve payment association ordering by ID and delivery association ordering by `orden` then ID in the loaded aggregate.
- [x] 2.3 Create `backend/services/configuracion_comercio_service.py` as a read-only service that returns the aggregate or raises existing `ComercioNotFound` without transaction finalization.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/configuracion_comercio.py` with `GET /comercios/{comercio_id}/configuracion`, aggregate response model, and commerce-not-found 404 mapping.
- [x] 3.2 Register the configuration router in `backend/main.py` without changing unrelated routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify existing-commerce success, all scalar fields, and nested status.
- [x] 4.2 Verify payment and delivery associations are commerce-scoped, include catalog records, and preserve required ordering.
- [x] 4.3 Verify empty association collections, missing-commerce 404, and absence of product-domain fields.
- [x] 4.4 Verify eager loading avoids per-association N+1 queries and the endpoint performs no writes.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.9 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run configuration integration tests against `supernova_test` and confirm the existing API smoke suite still passes (102/102).
- [x] 5.3 Run project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (compile passes; scoped checks report only baseline/dependency errors).
- [x] 5.4 Confirm models, migrations, write endpoints, authentication, and product-domain queries remain unchanged.
