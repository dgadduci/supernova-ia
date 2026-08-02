## Why

The `pedido` model (subphase 2.11) deferred any session relationship, and the `cliente` model (subphase 2.12) was the prerequisite. The system now needs a first-class `Session` entity that anchors every customer interaction: each pedido must belong to a session, and at most one active session may exist per `(comercio, cliente)` pair. Without it the API cannot enforce the "every order has a session" rule, nor expose the session lifecycle the WhatsApp channel needs.

## What Changes

- Add a `Session` SQLAlchemy model mapping to a new `sessions` table.
- Add an `EstadoSession` Python `enum.Enum` with values `activa` and `cerrada`; default `activa`.
- Add an Alembic migration that creates `sessions` and adds the required `id_session` column to `pedidos`.
- Modify the existing `Pedido` model: add a non-null `id_session` FK → `sessions.id` and a `session` `Mapped[Session]` relationship.
- Modify `PedidoCreate`: `id_session` becomes a required field. Update existing pedido tests to set up a session before posting.
- Add six sync FastAPI endpoints for the session lifecycle: create, get-by-id, get-active-by-comercio-cliente, update last movement, associate pedido, close.
- Enforce "one active session per (comercio, cliente)" via a partial unique index on `(id_comercio, id_cliente) WHERE estado_session = 'activa'`.
- Configure the circular FK between `sessions` and `pedidos` explicitly to avoid ambiguity:
  - `pedidos.id_session` (NOT NULL) — the owner side.
  - `sessions.id_pedido` (NULLABLE) — the optional current pedido pointer; declared with `post_update=True` so the migration can add the constraint after both tables exist.
- Bidirectional `Mapped[...]` relationships: `Session.comercio`, `Session.cliente`, `Session.pedido`; `Pedido.session`.

## Capabilities

### New Capabilities

- `session-api`: REST endpoints for the session lifecycle — create, retrieve (by id and by active comercio-cliente), update last movement, associate pedido, close.

### Modified Capabilities

- `pedido-api`: `id_session` is now a required field on `POST /pedidos`. Existing pedido create flows must be updated to set up a session first.

## Impact

- Adds `backend/models/session.py`, `backend/alembic/versions/<rev>_add_sessions_and_pedido_id_session.py`, `backend/routers/sessions.py`, `backend/schemas/session.py`, `backend/repositories/session_repository.py`, `backend/services/session_service.py`.
- Modifies `backend/models/pedido.py` (adds `id_session` + `session` relationship) and `backend/schemas/pedido.py` (adds `id_session` to `PedidoCreate` and `PedidoResponse`).
- Modifies `backend/services/pedido_service.py` (validates the supplied `id_session` exists and is `activa` before persisting a pedido).
- Modifies `backend/services/exceptions.py` (adds `SessionNotFound`, `DuplicateActiveSession`, `SessionNotActive`, `IncompatiblePedidoAssociation`, `SessionAlreadyClosed`).
- Modifies `backend/alembic/env.py` (imports `Session`).
- Modifies `backend/main.py` (registers `sessions.router`).
- Modifies `backend/tests/api_smoke.py` (existing pedido tests updated to set up a session; new session tests added).
- Affects both `supernova` and `supernova_test` via the new migration.