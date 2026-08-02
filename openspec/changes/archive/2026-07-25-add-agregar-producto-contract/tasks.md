## 1. Package and Contract Module

- [x] 1.1 Create the empty package marker `backend/intents/__init__.py`.
- [x] 1.2 Create the empty package marker `backend/intents/contracts/__init__.py`.
- [x] 1.3 Create `backend/intents/contracts/agregar_producto.py` exporting `AGREGAR_PRODUCTO_CONTRACT` as a `dict` literal with the exact shape and values from the spec:
  - `intent: "agregar_producto"`
  - `recognizer: "recognizer_productos"`
  - `handler: "agregar_producto"`
  - `requirements`:
    - `producto_presentacion_id: {"required": True, "default": None}`
    - `cantidad: {"required": True, "default": 1}`

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` (or a new dedicated test module under `backend/tests/`) that:
  - imports `AGREGAR_PRODUCTO_CONTRACT` and confirms it is a `dict`;
  - asserts the top-level keys are exactly `{"intent", "recognizer", "handler", "requirements"}`;
  - asserts the string values `intent == "agregar_producto"`, `recognizer == "recognizer_productos"`, `handler == "agregar_producto"`;
  - asserts `requirements` keys are exactly `{"producto_presentacion_id", "cantidad"}`;
  - asserts each requirement's `required` is `True` and the `default` matches the spec (`None` and `1` respectively);
  - asserts the only public symbol exported by the module is `AGREGAR_PRODUCTO_CONTRACT`;
  - asserts that no other module exists under `backend/intents/contracts/` (i.e. only `agregar_producto.py` and `__init__.py`).
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new test passes alongside the existing 210 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new files compile.