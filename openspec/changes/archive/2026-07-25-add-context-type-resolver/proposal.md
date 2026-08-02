## Why

Subphase 3.8 introduced the `ContextType` enum — a closed vocabulary of `Session` resolution contexts. The future dispatch path will read `session.context_type` to pick the right recognizer / processor / handler chain. But there is no function yet that *classifies* a runtime `ProcessedIntent` into a `ContextType`. Without a resolver, every future adapter that needs to decide "is the session waiting for the user to pick a product?" has to reinvent the same predicate. The system also has no canonical place that defines the rule "an intent waiting for product disambiguation is in `PRODUCT_SELECTION` context" — that rule is implicit and easy to get wrong. This subphase introduces the small, pure, well-defined function that closes that gap.

## What Changes

- Add `backend/intents/context/__init__.py` (empty package marker) and `backend/intents/context/context_type_resolver.py` exporting a single function `resolve_context_type(intent: ProcessedIntent) -> ContextType | None`.
- The function inspects a `ProcessedIntent` and returns `ContextType.PRODUCT_SELECTION` only when all three conditions hold: `intent.status == "pending_resolution"`, requirement `producto_presentacion_id` exists with `status == "pending"`, and `intent.candidate_ids` is non-empty. Every other case returns `None`.
- The function is **pure** — no I/O, no DB, no recognizer call, no handler invocation, no session mutation, no persistence.
- Add one test entry to `backend/tests/api_smoke.py` covering: pending product selection returns `PRODUCT_SELECTION`; missing candidates returns `None`; non-pending intent returns `None`; unrelated pending requirement returns `None`.

## Capabilities

### New Capabilities

- `context-type-resolver`: The pure classifier that maps a runtime `ProcessedIntent` to a `ContextType`. The future dispatch path will call this on the active intent in a `PendingIntents` state to decide which recognizer / processor / handler chain to invoke next.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/context/__init__.py` and `backend/intents/context/context_type_resolver.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no service code, no recognizer, no handler, no persistence. The function is pure.
- No new runtime dependencies.

## Dependencies

- Imports `ProcessedIntent` from `backend.intents.schemas.processed_intent` (subphase 3.3).
- Imports `ContextType` from `backend.sessions.enums.context_type` (subphase 3.8).
- Imports `RequirementState` for the per-requirement status check.
- No SQLAlchemy, Pydantic model instantiation, or HTTP.