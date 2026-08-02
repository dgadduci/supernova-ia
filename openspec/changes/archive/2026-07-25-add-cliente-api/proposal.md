## Why

The system needs a first-class `Cliente` entity to anchor the customer side of every commerce interaction. Subphase 2.13 (session model) will FK into `clientes.id`, and the WhatsApp channel that routes incoming orders needs a persistent identity per phone number. Without `clientes` the API cannot persist customer records at all.

## What Changes

- Add a `Cliente` SQLAlchemy model mapping to a new `clientes` table.
- Add an Alembic migration that creates the `clientes` table on both `supernova` and `supernova_test`.
- Add sync FastAPI endpoints for create, get-by-id, get-by-whatsapp, update, and activate/deactivate under the established `Router → Service → Repository → Model` layering.
- Normalize `whatsapp` to E.164 on the way in (service layer); the column itself stores the canonical form.
- Enforce `whatsapp` uniqueness at the DB level (`unique=True, index=True`).
- Do **not** add a `Session` relationship or any session-related logic — those land in Subphase 2.13.

## Capabilities

### New Capabilities

- `cliente-api`: REST endpoints for the customer lifecycle — create, retrieve (by id and by whatsapp), update, and activate/deactivate.

### Modified Capabilities

- None.

## Impact

- Adds `backend/models/cliente.py`, `backend/alembic/versions/<rev>_add_clientes_table.py`, `backend/routers/clientes.py`, `backend/schemas/cliente.py`, `backend/repositories/cliente_repository.py`, `backend/services/cliente_service.py`.
- Extends `backend/services/exceptions.py` with cliente-specific domain exceptions.
- Extends `backend/alembic/env.py` so autogenerate sees the new model.
- Affects both `supernova` and `supernova_test` databases via the new migration.
- No model renames, no breaking changes to existing endpoints.