## Why

Subphase 3.7 introduced the `PendingIntentService` (manages `session.pending_intents` JSON column). Subphase 3.8 introduced the `ContextType` enum. Subphase 3.9 introduced the `ContextTypeResolver` (classifies a `ProcessedIntent` into a `ContextType`). The system has no persistence surface for `context_type` on `Session` yet, and no canonical entry point that combines all three: validate the intent, resolve the context, persist the intent as active, set the context. Without a service, every future adapter that wants to "start a product-selection flow" has to call three things in the right order and remember to clear both fields on completion. The active subphase adds the `context_type` column to `Session` and introduces the small service that owns the entry-point flow.

## What Changes

- Add a `context_type` column to the `Session` model: `Mapped[str | None]` typed as `String(50)`, nullable, with no default (NULL for pre-migration rows). The column stores the string value of a `ContextType` (e.g. `"product_selection"`).
- Add an Alembic migration that adds the column to both `supernova` and `supernova_test` (nullable, no backfill — pre-existing rows are NULL).
- Add `backend/intents/context/pending_context_service.py` exporting two functions: `set_pending_intent(session, intent: ProcessedIntent) -> PendingIntents` and `clear_pending_context(session) -> None`.
- The service is **in-memory mutation**: it reads the current `session.pending_intents`, validates the intent, calls `resolve_context_type` (subphase 3.9), calls `set_active` (subphase 3.7) on the in-memory state, sets `session.context_type` to the resolved string, and returns the new `PendingIntents`. The caller is responsible for committing.
- Add one test entry to `backend/tests/api_smoke.py` covering: saving a valid pending product-selection intent, rejecting a non-pending intent, rejecting a pending intent without resolvable context, and clearing both `pending_intents` and `context_type`.

## Capabilities

### New Capabilities

- `pending-context-service`: The service that owns the entry-point flow that combines `PendingIntentService` + `ContextTypeResolver` + the new `context_type` column. The future dispatch path will call this when a new WhatsApp message arrives.

### Modified Capabilities

- None. (The `Session` model gains a new column, but the column is additive and the existing session endpoints do not read or write the new column.)

## Impact

- Adds `backend/intents/context/pending_context_service.py`.
- Modifies `backend/models/session.py` (adds one column).
- Adds one Alembic migration to `backend/alembic/versions/`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No router, no FastAPI endpoint, no recognizer, no handler. The service is in-memory mutation; the persistence is the model column.
- No new runtime dependencies.

## Dependencies

- `ProcessedIntent`, `PendingIntents` from `backend.intents.schemas.*` (subphases 3.3, 3.4).
- `resolve_context_type` from `backend.intents.context.context_type_resolver` (subphase 3.9).
- `set_active`, `clear` from `backend.intents.services.pending_intent_service` (subphase 3.7).
- `ContextType` from `backend.sessions.enums.context_type` (subphase 3.8).