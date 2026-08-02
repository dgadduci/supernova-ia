## Why

The project can now execute a ready `agregar_producto` intent, but the pending conversation context remains open afterward. Subphase 3.17 adds the lifecycle boundary that loads the active pending intent, dispatches the supported handler, and clears context only after successful execution.

## What Changes

- Add `execute_ready_pending_context(db, session) -> ProcessedIntent`.
- Load pending state through the existing pending-intent service.
- Require an active ready intent before handler execution.
- Dispatch the current `agregar_producto` handler only.
- Clear pending intents and context type after an `executed` result.
- Preserve pending context for rejected or failed results.
- Reject missing, non-ready, or unsupported active intents without commits, HTTP concerns, queries, or queue promotion.

## Capabilities

### New Capabilities
- `pending-context-execution`: Defines ready-intent dispatch and conditional context cleanup.

### Modified Capabilities

## Impact

- `backend/intents/orchestration/pending_context_execution.py`
- Existing pending-intent service, pending-context service, and agregar-producto handler integration
- Tests in `backend/tests/api_smoke.py`
- No handler, recognizer, repository, router, response, migration, or generic dispatcher changes.
