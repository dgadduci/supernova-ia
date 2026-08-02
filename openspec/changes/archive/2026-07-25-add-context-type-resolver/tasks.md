## 1. Resolver Module

- [x] 1.1 Create the empty package marker `backend/intents/context/__init__.py`.
- [x] 1.2 Create `backend/intents/context/context_type_resolver.py` exporting one function:
  - `resolve_context_type(intent: ProcessedIntent) -> ContextType | None` — pure, no I/O, no DB, no recognizer, no handler, no service.
  - Imports: `ProcessedIntent` from `backend.intents.schemas.processed_intent`; `RequirementState` from `backend.intents.schemas.requirement_state`; `ContextType` from `backend.sessions.enums.context_type`.
  - The function returns `ContextType.PRODUCT_SELECTION` only when **all three** conditions hold:
    1. `intent.status == "pending_resolution"`
    2. `intent.requirements` contains a `RequirementState` with `name == "producto_presentacion_id"` and `status == "pending"`
    3. `intent.candidate_ids` is non-empty (truthy)
  - Every other case returns `None`.
  - Declare `__all__ = ["resolve_context_type"]`.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `resolve_context_type`, `ContextType`, `ProcessedIntent`, `RequirementState`;
  - asserts all-three-conditions met returns `ContextType.PRODUCT_SELECTION` (covers the multi-candidate case and the single-candidate case);
  - asserts pending with `requirements=[producto_presentacion_id pending, cantidad pending]` and `candidate_ids=[1]` returns `ContextType.PRODUCT_SELECTION` (the function only checks `producto_presentacion_id`);
  - asserts empty `candidate_ids` returns `None`;
  - asserts each of `status in {"ready", "executed", "rejected", "failed"}` with the right pre-conditions returns `None`;
  - asserts `requirements=[]` returns `None`;
  - asserts `producto_presentacion_id` with `status="completed"` returns `None`;
  - asserts missing `producto_presentacion_id` (only `cantidad` present) returns `None`;
  - asserts the module's `__all__` is exactly `{"resolve_context_type"}`;
  - asserts the `context/` package contains only `__init__.py` and `context_type_resolver.py`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 302 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.