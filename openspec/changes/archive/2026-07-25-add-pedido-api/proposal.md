## Why

The system needs an order entity that represents a customer's request as it moves through its lifecycle. Without a persisted `pedido` model the API cannot capture order state, payment method, delivery method, or scheduled delivery time, which are the foundation for downstream WhatsApp intake and commerce routing.

## What Changes

- Add a `Pedido` SQLAlchemy model mapping to a new `pedidos` table.
- Add an Alembic migration that creates the `pedidos` table on both `supernova` and `supernova_test`.
- Add six sync FastAPI endpoints for create, get-by-id, and per-field updates under the established `Router → Service → Repository → Model` layering.
- Introduce a `estado_pedido` enum with values `borrador`, `ingresado`, `preparacion`, `terminado`, `entregado`, `cancelado`. New orders default to `borrador`.
- Enforce the rule that only `borrador` orders accept modifications; any update outside `borrador` returns 409.
- Enforce the allowed state transitions; invalid transitions return 409.
- Do **not** introduce a `sessions` relationship yet — it lands when the `session` model exists.

## Capabilities

### New Capabilities

- `pedido-api`: REST endpoints for the order lifecycle — creation, retrieval, and per-field updates (payment method, delivery method, scheduled delivery time, state).

### Modified Capabilities

- None.

## Impact

- Adds `backend/models/pedido.py`, `backend/alembic/versions/<rev>_add_pedidos_table.py`, `backend/routers/pedidos.py`, `backend/schemas/pedido.py`, `backend/repositories/pedido_repository.py`, `backend/services/pedido_service.py`.
- Extends `backend/services/exceptions.py` with pedido-specific domain exceptions.
- Extends `backend/alembic/env.py` so autogenerate sees the new model.
- Affects both `supernova` and `supernova_test` databases via the new migration.
- No model renames, no breaking changes to existing endpoints.