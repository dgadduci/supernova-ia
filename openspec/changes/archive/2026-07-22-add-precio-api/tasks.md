## 1. Schemas and Domain Errors

- [x] 1.1 Create `backend/schemas/precio.py` with decimal-safe `PrecioCreate` and `PrecioResponse`, forbidding extra fields, excluding `id_producto_presentacion`, rejecting negatives/excess scale, and enforcing `Numeric(12, 2)` precision.
- [x] 1.2 Extend `backend/services/exceptions.py` with product-presentation-not-found, price-not-found, duplicate-price, and invalid-price domain exceptions.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/precio_repository.py` with product-presentation existence lookup, price lookup by ID and association ID, and price creation without transaction control or relationship loading.
- [x] 2.2 Create `backend/services/precio_service.py` to verify associations, validate/quantize Decimal values, enforce one price per association, retrieve prices, commit success, and roll back failures.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/precios.py` with association-price retrieval/creation and direct price retrieval, response models, path ownership, and domain-to-HTTP exception mapping.
- [x] 3.2 Register the price router in `backend/main.py` without changing unrelated routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify exact Decimal creation, direct retrieval, and product-presentation price retrieval.
- [x] 4.2 Add tests for missing product-presentations, missing prices, existing association without price, body ownership rejection, and duplicate-price 409 behavior.
- [x] 4.3 Add validation tests for negative values, excess decimal places, and `Numeric(12, 2)` precision limits.
- [x] 4.4 Add or preserve coverage proving price creation rolls back on persistence failure and does not create or modify product-presentation rows.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.8 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run price integration tests against `supernova_test` and confirm the existing API smoke suite still passes.
- [x] 5.3 Run project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (scoped checks report only baseline/dependency errors; no new price implementation errors).
- [x] 5.4 Confirm `Precio` and `ProductoPresentacion` models, migrations, history, discounts, promotions, update/delete, and bulk-price behavior remain unchanged.
