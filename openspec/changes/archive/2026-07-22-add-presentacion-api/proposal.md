## Why

Subphase 2.6 exposes the existing `Presentacion` model through FastAPI so clients can manage commerce-owned product presentations before products are linked to them. The slice establishes the same nested ownership, validation, and transaction patterns used by Subphase 2.5 while enforcing presentation-specific code and description uniqueness within each commerce.

## What Changes

- Add presentation request and response schemas.
- Add repository and service operations for commerce checks, scoped listing, retrieval, creation, and duplicate detection.
- Add `GET /comercios/{comercio_id}/presentaciones`, `GET /presentaciones/{presentacion_id}`, and `POST /comercios/{comercio_id}/presentaciones`.
- Register the presentation router in the existing FastAPI application.
- Extend shared domain exceptions for missing presentations, duplicate codes, duplicate descriptions, and invalid input.
- Add minimum integration coverage against `supernova_test`.
- Mark and condense Subphase 2.6 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `presentacion-api`: HTTP API for listing, retrieving, and creating commerce-owned product presentations.

### Modified Capabilities

- None.

## Impact

- New files under `backend/routers/`, `backend/schemas/`, `backend/repositories/`, and `backend/services/`.
- Existing `backend/main.py`, shared domain exceptions, API integration tests, and `openspec/specs/project.md` are updated.
- No model changes, Alembic migrations, product-presentation association endpoints, or presentation update/delete operations.
