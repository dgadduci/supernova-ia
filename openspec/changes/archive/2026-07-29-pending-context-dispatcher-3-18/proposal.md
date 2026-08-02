## Why

The conversation runtime can now execute a ready `agregar_producto` intent, but no component routes incoming messages to the right per-context orchestration based on `session.context_type`. Subphase 3.18 adds a thin dispatcher that advances the active pending intent for `product_selection`, persists results, and triggers execution when the intent becomes ready.

## What Changes

- Add `dispatch_pending_context(db, session, message) -> ProcessedIntent`.
- Reuse `PendingIntentService` to load the active intent.
- Reject missing active intents or missing `session.context_type` with `status == "rejected"` and preserved state.
- Route `product_selection` through the existing product-selection orchestration service.
- Persist updated pending state when the result remains `pending_resolution`.
- Persist updated pending state when the result becomes `ready`, then delegate to `execute_ready_pending_context`.
- Reject unsupported or invalid context types without executing handlers or clearing context.

## Capabilities

### New Capabilities
- `pending-context-dispatcher`: Defines the conversation-routing entry point, context validation, dispatch transitions, and preservation boundaries.

### Modified Capabilities

## Impact

- `backend/intents/orchestration/pending_context_dispatcher.py`
- Existing `PendingIntentService`, product-selection orchestration service, and pending-context execution service integration
- Tests in `backend/tests/api_smoke.py`
- No router, migration, dependency, response, queue promotion, handler, recognizer, or generic dispatcher abstraction changes.
