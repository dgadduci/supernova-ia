## Why

Subphase 2.7 exposes the existing `Producto` model through FastAPI so clients can create products under categories and list catalog products by category or commerce. This completes the core product slice while preserving category ownership, model defaults, and deferred presentation/price concerns.

## What Changes

- Add product create and response schemas.
- Add repository and service operations for category/commerce checks, category- and commerce-scoped listings, retrieval, creation, and duplicate-name detection.
- Add four endpoints: category product listing, commerce product listing, product retrieval, and category-scoped product creation.
- Register the product router in the existing FastAPI application.
- Extend shared domain exceptions for missing products, duplicate names, and invalid input.
- Add integration coverage against `supernova_test`.
- Mark and condense Subphase 2.7 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `producto-api`: HTTP API for creating products under categories and listing/retrieving products by category, commerce, or product ID.

### Modified Capabilities

- None.

## Impact

- New files under `backend/routers/`, `backend/schemas/`, `backend/repositories/`, and `backend/services/`.
- Existing `backend/main.py`, shared exceptions, API integration tests, and `openspec/specs/project.md` are updated.
- No model changes, migrations, presentation associations, prices, availability mutations, update, or delete endpoints.
