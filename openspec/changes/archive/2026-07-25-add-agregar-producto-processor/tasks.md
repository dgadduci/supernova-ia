## 1. Processor Module

- [x] 1.1 Create `backend/intents/processor.py` exporting one function:
  - `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent` — pure, no I/O, no recognizer, no handler, no DB.
  - Imports: `AGREGAR_PRODUCTO_CONTRACT` from `backend.intents.contracts.agregar_producto`; `RequirementState` from `backend.intents.schemas.requirement_state`; `ProcessedIntent` from `backend.intents.schemas.processed_intent`.
  - Read `resolved_data` and `candidate_ids` from `normalized_result` (default to `{}` and `[]` if missing).
  - For each requirement name in `AGREGAR_PRODUCTO_CONTRACT["requirements"]`:
    - If the name is a key in `resolved_data`, build `RequirementState(name=name, status="completed", value=resolved_data[name])`.
    - Else, build `RequirementState(name=name, status="pending", value=requirements[name]["default"])`.
  - Decide `status`: `"ready"` iff every requirement with `requirements[name]["required"] is True` has `status="completed"`, else `"pending_resolution"`.
  - Build and return `ProcessedIntent(intent=AGREGAR_PRODUCTO_CONTRACT["intent"], source_text=source_text, status=status, recognizer=AGREGAR_PRODUCTO_CONTRACT["recognizer"], handler=AGREGAR_PRODUCTO_CONTRACT["handler"], resolved_data=resolved_data, requirements=requirements_list, candidate_ids=candidate_ids)`. The active subphase does NOT copy `unavailable_items` / `not_found_items` into the `ProcessedIntent` (those are not part of the schema yet — see the "Future work" note in `design.md`).
  - Declare `__all__ = ["process_agregar_producto"]`.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `process_agregar_producto`;
  - asserts the import returns a `ProcessedIntent` with the expected fields for a fully-populated input;
  - asserts all-required-completed returns `status == "ready"` and every `RequirementState` has `status == "completed"`;
  - asserts missing `producto_presentacion_id` returns `status == "pending_resolution"` and the corresponding `RequirementState` has `value is None`;
  - asserts missing `cantidad` returns `status == "pending_resolution"` and the corresponding `RequirementState` has `value == 1`;
  - asserts candidate IDs round-trip verbatim;
  - asserts `unavailable_items` and `not_found_items` round-trip verbatim (the active subphase does not include them in the `ProcessedIntent` — they live on the `normalized_result` and the test asserts they round-trip via the input, not the output);
  - asserts `source_text` is preserved;
  - asserts `recognizer == "recognizer_productos"` and `handler == "agregar_producto"`;
  - asserts the returned value passes a `ProcessedIntent.model_validate(result.model_dump())` round-trip;
  - asserts the module's `__all__` is `{"process_agregar_producto"}`;
  - asserts `processor.py` is the only new file in `backend/intents/`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 263 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.