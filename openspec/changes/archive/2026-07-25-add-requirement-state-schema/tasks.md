## 1. Package and Schema Module

- [x] 1.1 Create the empty package marker `backend/intents/schemas/__init__.py`.
- [x] 1.2 Create `backend/intents/schemas/requirement_state.py` exporting two symbols:
  - `RequirementStatus: Literal["pending", "completed"]`
  - `RequirementState(BaseModel)` with three fields in order: `name: str`, `status: RequirementStatus`, `value: Any | None = None`
  Use Pydantic's `BaseModel` and `typing.Literal` / `typing.Any` from the standard library. Do NOT add `model_config`, validators, methods, or any business logic.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `RequirementState` and `RequirementStatus`;
  - asserts valid creation with explicit `name`, `status`, and `value`;
  - asserts `value` defaults to `None` when omitted (covers both `"pending"` and `"completed"` statuses);
  - asserts the constructor raises `pydantic.ValidationError` for an invalid `status` (e.g. `"unknown"`);
  - asserts the constructor raises `pydantic.ValidationError` when `name` is missing or non-string;
  - asserts that the only public symbols exported by the module are `RequirementState` and `RequirementStatus`;
  - asserts that `requirement_state.py` is the only non-package file under `backend/intents/schemas/`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 220 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new files compile.