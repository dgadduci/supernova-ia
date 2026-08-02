## 1. Schemas and Domain Errors

- [x] 1.1 Create `backend/schemas/metodo_entrega.py` with `MetodoEntregaCreate` and `MetodoEntregaResponse`, forbidding extra create fields, requiring non-negative `orden`, defaulting `activo` to true, and enabling ORM serialization.
- [x] 1.2 Extend `backend/services/exceptions.py` with delivery-method not-found, duplicate-code, and invalid-input domain exceptions following existing resource patterns.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/metodo_entrega_repository.py` with `list_all`, `get_by_id`, `get_by_codigo`, and `create`, ordering lists by id and leaving transaction control to the service.
- [x] 2.2 Create `backend/services/metodo_entrega_service.py` to trim and validate text, detect duplicate codes, retrieve rows, commit successful creation, and roll back persistence failures.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/metodos_entrega.py` with `GET /metodos-entrega`, `GET /metodos-entrega/{metodo_entrega_id}`, and `POST /metodos-entrega`, including response schemas and domain-to-HTTP exception mapping.
- [x] 3.2 Register the delivery-method router in `backend/main.py` without changing existing routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify list ordering, retrieval success, and missing-id 404 behavior against `supernova_test`.
- [x] 4.2 Add create tests covering 201 persistence, whitespace trimming, default and explicit `activo`, and duplicate-code 409 behavior.
- [x] 4.3 Add validation tests covering empty-after-trim text, negative `orden`, and forbidden database-managed or undeclared fields.
- [x] 4.4 Add or preserve coverage proving failed creation rolls back and leaves no partial row.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.4 section in `openspec/specs/project.md` with a checked, condensed implementation summary that preserves context needed by later subphases.
- [x] 5.2 Run the delivery-method integration tests against `supernova_test` and confirm all existing API tests still pass.
- [x] 5.3 Run the project lint and type-check commands defined by the repository, or record that none are configured (scoped checks report only pre-existing baseline/dependency errors; no new delivery-method implementation errors).
- [x] 5.4 Confirm the `MetodosEntrega` model, Alembic migrations, authentication, pagination, update/delete operations, and commerce-delivery association APIs remain unchanged.
