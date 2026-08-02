## Why

Subphase 3.1 introduced a static `dict` contract for the `agregar_producto` intent. The contract declares `requirements` as a `dict` of `{required, default}` entries, but the runtime side of the system has no typed representation of a single requirement's state. Without a Pydantic schema for `RequirementState` the future recognizer/handler adapters have nothing to validate against, no consistent shape to populate, and no stable contract to test.

## What Changes

- Add `backend/intents/schemas/__init__.py` (empty package marker).
- Add `backend/intents/schemas/requirement_state.py` exporting two symbols: `RequirementStatus` (a `Literal["pending", "completed"]`) and `RequirementState` (a Pydantic `BaseModel`).
- `RequirementState` carries `name: str`, `status: RequirementStatus`, and `value: Any | None = None`. The `value` defaults to `None` so a freshly-instantiated state is empty until the recognizer or handler populates it.
- Add one test module entry to `backend/tests/api_smoke.py` covering: valid creation, default `value=None`, and rejection of an invalid `status`.

## Capabilities

### New Capabilities

- `requirement-state-schema`: A Pydantic schema that the future recognizer and handler adapters will use to track and validate the state of a single contract requirement at runtime.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/schemas/__init__.py` and `backend/intents/schemas/requirement_state.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no service code, no other intent contracts, no registry, no recognizer, no handler. The schema is a typed value object only.
- No new runtime dependencies — Pydantic is already used across the project.