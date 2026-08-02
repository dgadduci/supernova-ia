## 1. Schema Module

- [x] 1.1 Create `backend/intents/schemas/pending_intents.py` exporting one symbol and a `__all__`:
  - `PendingIntents(BaseModel)` with three fields in this order, using the exact types and defaults from the spec:
    - `version: int = 1`
    - `active: ProcessedIntent | None = None`
    - `queue: list[ProcessedIntent] = Field(default_factory=list)`
  - Import `ProcessedIntent` from `backend.intents.schemas.processed_intent`.
  - Use Pydantic `BaseModel` and `Field` (no `model_config`, no methods, no validators beyond default type checks).
  - Declare `__all__ = ["PendingIntents"]`.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `PendingIntents`;
  - asserts default creation: `version == 1`, `active is None`, `queue == []`;
  - asserts default `queue` is not shared across instances (mutating one does not affect the other);
  - asserts creation with an `active` `ProcessedIntent` and a non-empty `queue`;
  - asserts nested validation: an `active` with an invalid `status` raises `pydantic.ValidationError`;
  - asserts nested validation: a `queue` member with an invalid `status` raises `pydantic.ValidationError`;
  - asserts nested validation: an `active` missing a required field raises `pydantic.ValidationError`;
  - asserts JSON round-trip via `model_dump(mode="json")` and `PendingIntents.model_validate(...)` preserves `version`, `active.intent`, `active.status`, and the queue's intent names in order;
  - asserts the default instance round-trips to `version == 1`, `active is None`, `queue == []`;
  - asserts `model_dump(mode="json")` returns a plain `dict` of JSON-serializable values (no `Decimal`, `datetime`, etc.);
  - asserts the module's `__all__` is `{"PendingIntents"}`;
  - asserts `pending_intents.py` is the only new file in the schemas package, and the schemas package now contains exactly `{"requirement_state.py", "processed_intent.py", "pending_intents.py"}`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 236 tests. Update the prior subphase's "only schema file" test if necessary.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.