## Why

Subphase 3.4 introduced `PendingIntents` as the conversation-wide state object. The system has no persistence surface for it yet, and no canonical mutation path. Without a service, every future adapter that needs to set the active intent, enqueue another, or promote the queue head has to reinvent the same JSON serialization and the same mutation rules — and the `pending_intents` field does not yet exist on the `Session` model. This subphase introduces both: a `pending_intents` JSON column on `Session` and a service that owns the read/write/promote lifecycle.

## What Changes

- Add `pending_intents` column to the `Session` SQLAlchemy model: `Text`, nullable, with server default `"{}"`. The column stores a JSON-serialized `PendingIntents` (the spec describes it as "JSON-compatible").
- Add an Alembic migration that adds the column to both `supernova` and `supernova_test` (with a backfill default of `"{}"` for any pre-existing rows).
- Add `backend/intents/services/__init__.py` (empty package marker) and `backend/intents/services/pending_intent_service.py` exporting five module-level functions: `load`, `set_active`, `enqueue`, `remove_active`, `clear`.
- The service operates on a `Session` model instance passed by argument (not on a SQLAlchemy `Session` transaction — the parameter is named `session` in the spec). Each mutation deserializes the current state, applies the change, serializes with `model_dump(mode="json")`, and writes back to `session.pending_intents`. The service does not commit, query repositories, execute handlers, or manage transactions; the caller is responsible.
- Add one test entry to `backend/tests/api_smoke.py` covering: loading an empty session, setting the active intent, enqueueing an intent, promoting the queue after removing the active intent, and clearing pending intents.

## Capabilities

### New Capabilities

- `pending-intent-service`: The service that owns the lifecycle of the `PendingIntents` conversation state on each `Session` row. Future dispatch / handler subphases will call this service to advance the state machine.

### Modified Capabilities

- None. (The `Session` model gains a new column, but the column is additive: existing `Session` rows default to `"{}"`, and the existing session endpoints do not read or write the new column.)

## Impact

- Adds `backend/intents/services/__init__.py` and `backend/intents/services/pending_intent_service.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- Modifies `backend/models/session.py` (adds one column).
- Adds one Alembic migration to `backend/alembic/versions/`.
- No router, no FastAPI endpoint, no service code, no recognizer, no handler. The service is in-memory mutation; the persistence is the model column.
- No new runtime dependencies.