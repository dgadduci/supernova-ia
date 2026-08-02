## 1. Schemas and Domain Errors

- [x] 1.1 Create `backend/schemas/categoria_producto.py` with `CategoriaProductoCreate` and `CategoriaProductoResponse`, forbidding extra fields, excluding `id_comercio`, validating description length, and rejecting negative supplied `orden`.
- [x] 1.2 Extend `backend/services/exceptions.py` with category-not-found and invalid-category domain exceptions, reusing the existing commerce-not-found exception.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/categoria_producto_repository.py` with commerce existence lookup, commerce-scoped category listing ordered by `orden` then `id`, category lookup by id, and category creation without transaction control or relationship loading.
- [x] 2.2 Create `backend/services/categoria_producto_service.py` to verify commerce ownership, trim and validate descriptions, preserve omitted model defaults, create categories with route-derived commerce IDs, commit success, and roll back failures.

## 3. Router and Application Wiring

- [x] 3.1 Create `backend/routers/categorias_productos.py` with nested list/create routes and direct category retrieval, response models, path-parameter ownership, and domain-to-HTTP exception mapping.
- [x] 3.2 Register the product-category router in `backend/main.py` without changing unrelated routes.

## 4. Integration Tests

- [x] 4.1 Extend `backend/tests/api_smoke.py` to verify category creation, direct retrieval, and commerce-scoped listing ordered by `orden` then `id`.
- [x] 4.2 Add tests for commerce ownership isolation, missing commerce 404 responses, missing category 404 responses, and rejection of body `id_comercio`.
- [x] 4.3 Add validation and default tests covering trimmed/empty descriptions, negative `orden`, omitted defaults, and explicit `activo`/`orden` values.
- [x] 4.4 Add or preserve coverage proving category creation rolls back on persistence failure and does not create products.

## 5. Project Context and Verification

- [x] 5.1 Replace the Subphase 2.5 section in `openspec/specs/project.md` with a checked, condensed implementation summary without modifying other phases or subphases.
- [x] 5.2 Run the product-category integration tests against `supernova_test` and confirm the existing API smoke suite still passes.
- [x] 5.3 Run the project lint and type-check commands, reporting pre-existing baseline errors without fixing unrelated files (scoped checks report only baseline/dependency errors; no new category implementation errors).
- [x] 5.4 Confirm `CategoriaProducto` and `Comercio` models, Alembic migrations, product endpoints, update/delete operations, and product associations remain unchanged.
