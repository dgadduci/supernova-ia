## Why

Subphase 3.3 introduced `ProcessedIntent` — the typed envelope for one processed intent at one moment. A WhatsApp conversation may have *several* intents in flight at once: the user may be in the middle of an `agregar_producto` flow (the active one) and have other `agregar_producto` invocations queued behind it. Without a typed value object that represents the conversation-wide "pending intents" state, every recognizer/handler has to invent its own ad-hoc shape for the queue. The system also needs a JSON-round-trippable form so a future subphase can persist the state on the `Session` row and resume after an interruption.

## What Changes

- Add `backend/intents/schemas/pending_intents.py` exporting a single `PendingIntents` Pydantic `BaseModel` and a `__all__`.
- `PendingIntents` carries three fields: `version: int = 1`, `active: ProcessedIntent | None = None`, and `queue: list[ProcessedIntent] = Field(default_factory=list)`.
- The schema is a pure value object — no methods, no validators beyond Pydantic's default type checks, no business logic.
- Add one test entry to `backend/tests/api_smoke.py` covering: default creation, creation with an active and queued intents, nested `ProcessedIntent` validation, and a JSON round-trip via `model_dump(mode="json")` and `model_validate()`.

## Capabilities

### New Capabilities

- `pending-intents-schema`: The typed value object that represents the conversation-wide state of one (or several) processed intents in flight. Future subphases will serialize it to JSON for persistence and resume on reconnects.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/schemas/pending_intents.py` (no new `__init__.py` — the package marker from subphase 3.2 is sufficient).
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no service code, no recognizer, no handler, no persistence. The schema is a typed value object only.
- No new runtime dependencies.