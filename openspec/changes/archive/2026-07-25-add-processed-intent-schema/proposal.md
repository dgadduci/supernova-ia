## Why

Subphase 3.1 introduced the static `dict` contract for an intent. Subphase 3.2 introduced a typed `RequirementState` for tracking one requirement's state at runtime. The system still has no typed value object that represents the *whole* processed intent at runtime — the thing the recognizer produces and the handler consumes. Without a `ProcessedIntent` schema, every adapter has to invent its own ad-hoc shape, and there is no canonical "what an intent looks like once it has been processed" type for tests to pin.

## What Changes

- Add `backend/intents/schemas/processed_intent.py` exporting two symbols: `IntentStatus` (a `typing.Literal`) and `ProcessedIntent` (a Pydantic `BaseModel`).
- `ProcessedIntent` carries the full runtime state of one processed intent: its `intent` name, the `source_text` it was extracted from, the `status` of the resolution flow, the `recognizer` and `handler` names, the `resolved_data` extracted slots, the `requirements` states produced by the recognizer, and a list of `candidate_ids` for ambiguous cases.
- The schema is a pure value object — no methods, no validators beyond Pydantic's default type checks, no business logic.
- Add one test entry to `backend/tests/api_smoke.py` covering: valid creation, default empty collections, nested `RequirementState` validation, and rejection of an invalid `status`.

## Capabilities

### New Capabilities

- `processed-intent-schema`: The typed value object that the future recognizer and handler adapters use to represent one processed intent at runtime.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/schemas/processed_intent.py` (no new `__init__.py` — the package marker from subphase 3.2 is sufficient).
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no service code, no registry, no recognizer, no handler. The schema is a typed value object only.
- No new runtime dependencies.