## Why

Subphase 2.10 adds read-only product-query endpoints that aggregate product, category, presentation, and price data, while reusing the existing lightweight product endpoints. This supports catalog browsing, search, availability/sellable filtering, and admin detection of incomplete products without duplicating existing routes.

## What Changes

- Add read-only product detail, catalog, presentation, and price query endpoints.
- Reuse the existing `Producto`, `CategoriaProducto`, `Presentacion`, and `Precio` relationships without modifying models.
- Reuse or extend the existing product router, schemas, repository, and service; add query-specific modules only when responsibilities would otherwise mix.
- Provide category and product filter parameters with default active/available scoping for catalog browsing.
- Distinguish available, sellable, and incomplete products through deterministic repository queries.
- Add integration coverage against `supernova_test` without duplicating scenarios covered by earlier subphases.
- Mark and condense Subphase 2.10 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `producto-queries-api`: Read-only aggregation of product, category, presentation, and price data, plus catalog/search/availability filtering and admin detection of incomplete products.

### Modified Capabilities

- None.

## Impact

- Adds query-specific schemas, repository, service, and router modules where reuse is impossible.
- Extends the existing product router registration in `backend/main.py` and the API integration tests in `backend/tests/api_smoke.py`.
- No model changes, migrations, writes, authentication, or writeback behavior.
