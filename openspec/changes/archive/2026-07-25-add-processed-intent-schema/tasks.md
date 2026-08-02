## 1. Schema Module

- [x] 1.1 Create `backend/intents/schemas/processed_intent.py` exporting two symbols and a `__all__`:
  - `IntentStatus = Literal["pending_resolution", "ready", "executed", "rejected", "failed"]`
  - `ProcessedIntent(BaseModel)` with eight fields in this order, using the exact types and default factories from the spec:
    - `intent: str`
    - `source_text: str`
    - `status: IntentStatus`
    - `recognizer: str | None = None`
    - `handler: str`
    - `resolved_data: dict[str, Any] = Field(default_factory=dict)`
    - `requirements: list[RequirementState] = Field(default_factory=list)`
    - `candidate_ids: list[int] = Field(default_factory=list)`
  - Import `RequirementState` from `backend.intents.schemas.requirement_state`.
  - Use Pydantic `BaseModel` and `Field` (no `model_config`, no methods, no validators beyond default type checks).

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `ProcessedIntent` and `IntentStatus`;
  - asserts valid creation with every field supplied, including a `RequirementState` and `candidate_ids`;
  - asserts the three collection fields default to empty `{}` / `[]` / `[]`;
  - asserts `recognizer` defaults to `None`;
  - asserts that mutating one instance's `resolved_data` does not affect another instance (default factory isolation);
  - asserts a `RequirementState` with an invalid `status` raises `pydantic.ValidationError`;
  - asserts a valid `RequirementState` round-trips through the nested field;
  - asserts an invalid `status` on `ProcessedIntent` itself raises `pydantic.ValidationError`;
  - asserts a missing required field raises `pydantic.ValidationError`;
  - asserts the module's `__all__` is `{"IntentStatus", "ProcessedIntent"}`;
  - asserts `processed_intent.py` is the only new file in the schemas package.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 228 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.