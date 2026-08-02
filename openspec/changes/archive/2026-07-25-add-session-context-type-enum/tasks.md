## 1. Enum Module

- [x] 1.1 Create the empty package marker `backend/sessions/__init__.py`.
- [x] 1.2 Create the empty package marker `backend/sessions/enums/__init__.py`.
- [x] 1.3 Create `backend/sessions/enums/context_type.py` exporting one `ContextType` enum (a `StrEnum`) with exactly one member and a `__all__`:
  - `class ContextType(StrEnum):`
    - `PRODUCT_SELECTION = "product_selection"`
  - `__all__ = ["ContextType"]`
  - Do NOT create `backend/sessions/enums.py`. Do NOT add other values or business logic.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `ContextType`;
  - asserts the enum has exactly one member, `ContextType.PRODUCT_SELECTION`, with value `"product_selection"`;
  - asserts `ContextType.PRODUCT_SELECTION == "product_selection"`, `isinstance(ContextType.PRODUCT_SELECTION, str)`, and `str(ContextType.PRODUCT_SELECTION) == "product_selection"`;
  - asserts `ContextType("unknown")`, `ContextType("Product_Selection")` (different case), and `ContextType("")` all raise `ValueError`;
  - asserts the module's `__all__` is exactly `{"ContextType"}`;
  - asserts `backend/sessions/enums.py` does not exist (it is a *package*, not a single module);
  - asserts `backend/sessions/enums/` contains only `__init__.py` and `context_type.py`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 291 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new files compile.