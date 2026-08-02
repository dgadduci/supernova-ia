## Why

Subphase 2.4 must expose the existing `MetodosEntrega` catalog through the FastAPI layer so clients can list, retrieve, and create delivery methods using the established resource-slice architecture. This continues Phase 2 with the next catalog resource while preserving the model and database schema.

## What Changes

- Add request and response schemas for delivery methods.
- Add repository and service operations for listing, retrieving, and creating delivery methods.
- Add `GET /metodos-entrega`, `GET /metodos-entrega/{metodo_entrega_id}`, and `POST /metodos-entrega` endpoints.
- Register the delivery-method router in the existing FastAPI application.
- Extend shared domain exceptions as needed and map validation, not-found, and duplicate failures to HTTP responses.
- Add minimum integration coverage against `supernova_test`.
- Mark and condense Subphase 2.4 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `metodos-entrega-api`: Synchronous HTTP API for listing, retrieving, and creating delivery methods through the existing Router → Service → Repository → Model layering.

### Modified Capabilities

- None.

## Impact

- New files under `backend/routers/`, `backend/schemas/`, `backend/repositories/`, and `backend/services/`.
- Existing `backend/main.py`, shared domain exceptions, API integration tests, and `openspec/specs/project.md` are updated.
- No SQLAlchemy model changes, Alembic migrations, authentication, pagination, update/delete endpoints, or commerce-delivery association endpoints.
