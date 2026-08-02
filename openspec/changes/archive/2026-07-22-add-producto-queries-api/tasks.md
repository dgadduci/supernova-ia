## 1. Reuse Audit and Shared Schemas

- [x] 1.1 Audit existing `productos` router, repository, service, and tests; document which existing methods cover new endpoints and which are missing.
- [x] 1.2 Add only missing response schemas for product detail, catalog, presentations detail, price summary, search, available, sellable, incomplete, and category detail; reuse existing scalar schemas when possible.

## 2. Repository and Service

- [x] 2.1 Add only missing product-query repository methods with eager loading and deterministic ordering.
- [x] 2.2 Add only missing read-only service methods that verify required parent records, raise existing domain exceptions, and return loaded data.
- [x] 2.3 Implement commerce-scoped free-text search and exact-name lookup with case-insensitive matching.

## 3. Router and Application Wiring

- [x] 3.1 Add a new query router with the listed endpoints placed before any conflicting dynamic patterns.
- [x] 3.2 Register the query router in `backend/main.py` without modifying unrelated routes.

## 4. Integration Tests

- [x] 4.1 Verify product detail and category detail return only records belonging to the requested parent.
- [x] 4.2 Verify commerce catalog applies active and available filters with deterministic ordering.
- [x] 4.3 Verify product presentation listing, specific association, and association price endpoints.
- [x] 4.4 Verify free-text search and exact-name lookup are commerce-scoped and preserve Decimal precision.
- [x] 4.5 Verify available, sellable, and incomplete product detection returns only matching products.
- [x] 4.6 Verify existing lightweight product endpoints remain functional.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.10 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run product query integration tests against `supernova_test` and confirm the existing API smoke suite still passes (120/120).
- [x] 5.3 Run project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (compile passes; scoped checks report only baseline/dependency errors).
- [x] 5.4 Confirm models, migrations, write endpoints, authentication, and unrelated routes remain unchanged.
