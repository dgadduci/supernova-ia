## Why

Subphase 2.5 exposes the existing `CategoriaProducto` model through the FastAPI layer so clients can manage product categories within a commerce and retrieve individual categories. This adds the next commerce-owned catalog slice while preserving model defaults, ownership boundaries, and the established resource layering.

## What Changes

- Add request and response schemas for product categories.
- Add repository and service operations for commerce existence checks, category listing, retrieval, and creation.
- Add `GET /comercios/{comercio_id}/categorias-productos`, `GET /categorias-productos/{categoria_producto_id}`, and `POST /comercios/{comercio_id}/categorias-productos`.
- Register the product-category router in the existing FastAPI application.
- Extend shared domain exceptions for missing commerce and missing category cases.
- Add minimum integration coverage against `supernova_test`.
- Mark and condense Subphase 2.5 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `categoria-producto-api`: HTTP API for listing commerce-owned product categories, retrieving a category, and creating a category under a commerce.

### Modified Capabilities

- None.

## Impact

- New files under `backend/routers/`, `backend/schemas/`, `backend/repositories/`, and `backend/services/`.
- Existing `backend/main.py`, shared domain exceptions, API integration tests, and `openspec/specs/project.md` are updated.
- No SQLAlchemy model changes, Alembic migrations, product endpoints, category update/delete endpoints, or product associations.
