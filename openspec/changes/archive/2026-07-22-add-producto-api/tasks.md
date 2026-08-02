## 1. Schemas and Domain Errors

- [x] 1.1 Create `backend/schemas/producto.py` with `ProductoCreate` and `ProductoResponse`, forbidding extra fields, excluding `id_categoria_producto`, validating name length, allowing nullable description, and rejecting negative supplied `orden`.
- [x] 1.2 Extend `backend/services/exceptions.py` with product-not-found, duplicate-product-name, and invalid-product exceptions, reusing existing commerce/category not-found exceptions.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/producto_repository.py` with category/commerce existence checks, category-scoped ordered listing, commerce-scoped joined ordered listing, product retrieval, case-insensitive category-scoped name lookup, and creation without transaction control or relationship loading.
- [x] 2.2 Create `backend/services/producto_service.py` to validate ownership, trim names, normalize optional descriptions, enforce category-scoped duplicates, preserve omitted model defaults, create with route-derived category IDs, commit success, and roll back failures.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/productos.py` with category listing/creation, commerce listing, direct retrieval, response models, path ownership, and domain-to-HTTP exception mapping.
- [x] 3.2 Register the product router in `backend/main.py` without changing unrelated routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify product creation, defaults, description normalization, direct retrieval, and category-scoped ordering.
- [x] 4.2 Add commerce-list tests for ownership isolation and category/product ordering, including empty existing commerce and missing commerce behavior.
- [x] 4.3 Add missing-category/product, body ownership rejection, empty-name, negative-order, scoped duplicate-name, and cross-category same-name tests.
- [x] 4.4 Add or preserve coverage proving product creation rolls back on persistence failure and creates no presentation associations.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.7 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run product integration tests against `supernova_test` and confirm the existing API smoke suite still passes.
- [x] 5.3 Run project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (scoped checks report only baseline/dependency errors; no new product implementation errors).
- [x] 5.4 Confirm `Producto`, `CategoriaProducto`, and `Comercio` models, migrations, presentation associations, prices, update/delete, and availability endpoints remain unchanged.
