## Why

Subphase 2.8 exposes the existing `Precio` model through FastAPI so each product-presentation combination can receive and retrieve its single current price with exact decimal semantics. This completes the price layer while keeping price history, discounts, and product-presentation creation out of scope.

## What Changes

- Add decimal-safe price create and response schemas.
- Add repository and service operations for product-presentation existence, price lookup, uniqueness enforcement, and creation.
- Add `GET /producto-presentaciones/{producto_presentacion_id}/precio`, `GET /precios/{precio_id}`, and `POST /producto-presentaciones/{producto_presentacion_id}/precio`.
- Register the price router in the existing FastAPI application.
- Extend shared exceptions for missing product-presentations, missing prices, duplicate prices, and invalid values.
- Add integration coverage against `supernova_test`.
- Mark and condense Subphase 2.8 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `precio-api`: HTTP API for creating and retrieving the single decimal price associated with a product-presentation record.

### Modified Capabilities

- None.

## Impact

- New files under `backend/routers/`, `backend/schemas/`, `backend/repositories/`, and `backend/services/`.
- Existing `backend/main.py`, shared exceptions, API integration tests, and `openspec/specs/project.md` are updated.
- No model changes, migrations, product-presentation creation, history, discount, promotion, update, delete, or bulk-price behavior.
