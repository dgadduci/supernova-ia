## 1. Resolver Module

- [ ] 1.1 Create `backend/intents/context/product_selection_context_resolver.py` exporting one function and a `__all__`:
  - `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` — pure (does not commit, flush, close, mutate the session model, log, call handlers, or generate responses).
  - Imports: `ProcessedIntent` from `backend.intents.schemas.processed_intent`; `RequirementState` from `backend.intents.schemas.requirement_state`; `detectar_productos` from `backend.recognizers.product_recognizer`; `ProductoPresentacion` from `backend.models.producto_presentacion`; `select` and `joinedload` from `sqlalchemy`; `Session` from `sqlalchemy.orm` (TYPE_CHECKING only).
  - The function:
    1. Validates `active_intent.status == "pending_resolution"` AND `len(active_intent.candidate_ids) > 0`. If either fails, returns `active_intent` unchanged.
    2. Queries `select(ProductoPresentacion).options(joinedload(ProductoPresentacion.producto).joinedload(Producto.categoria), joinedload(ProductoPresentacion.presentacion)).where(ProductoPresentacion.id.in_(active_intent.candidate_ids))` against the `db` session.
    3. Builds the 12-field catalog list per row (the existing `ProductRecognizer.detectar_productos` input contract):
       - `producto_presentacion_id`: `pp.id`
       - `producto_id`: `pp.id_producto`
       - `presentacion_id`: `pp.id_presentacion`
       - `categoria_id`: `pp.producto.id_categoria_producto`
       - `producto_nombre`: `pp.producto.nombre`
       - `categoria_nombre`: `pp.producto.categoria.descripcion`
       - `presentacion_codigo`: `pp.presentacion.codigo`
       - `presentacion_descripcion`: `pp.presentacion.descripcion`
       - `producto_activo`: `bool(pp.producto.activo)` (DB `producto.activo`)
       - `presentacion_activo`: `bool(pp.presentacion.activo)` (DB `presentacion.activo`)
       - `activo`: `bool(pp.activo)` (DB `producto_presentacion.activo`)
       - `disponible`: `bool(pp.producto.disponible)` (DB `producto.disponible`)
    4. Calls `resultado = detectar_productos(message, productos_presentaciones)`.
    5. If `len(resultado["encontrados"]) != 1`, returns `active_intent` unchanged.
    6. If `resultado["encontrados"][0]["producto_presentacion_id"] not in active_intent.candidate_ids`, returns `active_intent` unchanged.
    7. Otherwise builds a new `ProcessedIntent` with:
       - `intent=active_intent.intent`
       - `source_text=active_intent.source_text`
       - `status="ready"` if every required requirement is `completed`, else `active_intent.status`
       - `recognizer=active_intent.recognizer`
       - `handler=active_intent.handler`
       - `resolved_data={**active_intent.resolved_data, "producto_presentacion_id": selected_id}` (preserves the original `cantidad` and other fields)
       - `requirements` with the `producto_presentacion_id` requirement updated to `status="completed"` and `value=selected_id`; other requirements unchanged
       - `candidate_ids=[]` (cleared after selection)
  - Returns the new `ProcessedIntent` from step 7.
  - `__all__ = ["resolve_product_selection"]`.

## 2. Verification

- [ ] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `resolve_product_selection`, `ProcessedIntent`, `RequirementState`;
  - patches `backend.intents.context.product_selection_context_resolver.detectar_productos` with a mock that returns a controllable dict;
  - uses a SQLAlchemy in-memory SQLite database (e.g. `engine = create_engine("sqlite:///:memory:")`, `Base.metadata.create_all(engine)`, `sessionmaker(bind=engine)`) to set up a real DB; inserts sample `ProductoPresentacion` rows joined to `Producto`, `Presentacion`, `CategoriaProducto`; do NOT use the project's `supernova_test` DB to keep the test isolated;
  - asserts the function issues a SQLAlchemy query with `.where(id.in_(...))` filtered to `active_intent.candidate_ids` (verified by inspecting the query or by inserting only matching rows and asserting they appear, plus an extra non-matching row that does NOT appear in the result);
  - asserts unique selection by presentation: the mock returns a single `encontrados` item with `producto_presentacion_id` in `candidate_ids`; the function returns a new `ProcessedIntent` with `producto_presentacion_id` set, the requirement marked `completed`, `candidate_ids=[]`, and the original `resolved_data` (including `cantidad`) preserved;
  - asserts the function calls `detectar_productos` exactly once with the user `message` and the built 12-field catalog;
  - asserts original `cantidad` is preserved;
  - asserts ambiguous result (2+ items in `encontrados`) returns `active_intent` unchanged;
  - asserts unavailable result (only `encontrados_no_disponibles` populated) returns `active_intent` unchanged;
  - asserts unknown result (no `encontrados`) returns `active_intent` unchanged;
  - asserts selected ID outside original `candidate_ids` returns `active_intent` unchanged;
  - asserts fully resolved intent has `status="ready"` when only `producto_presentacion_id` is required; asserts status stays the input status when another required requirement is still pending;
  - asserts the function does NOT call `db.commit` (verified by mock);
  - asserts the function does NOT modify the `active_intent` instance (the same object is returned when no resolution happens);
  - asserts the module's `__all__` is exactly `{"resolve_product_selection"}`;
  - asserts `backend/intents/context/` contains exactly `__init__.py`, `context_type_resolver.py`, `pending_context_service.py`, and `product_selection_context_resolver.py`.
- [ ] 2.2 Add a separate test entry to `backend/tests/api_smoke.py` that is a real integration test with the actual recognizer:
  - uses a SQLAlchemy in-memory SQLite database (e.g. `engine = create_engine("sqlite:///:memory:")`, `Base.metadata.create_all(engine)`, `sessionmaker(bind=engine)`) to set up a real DB; inserts two `ProductoPresentacion` rows for the same product (e.g. `Pizza Mozzarella`) with different presentations ("chica" and "grande") plus a third `ProductoPresentacion` row for a different product that should NOT be selected; do NOT use the project's `supernova_test` DB;
  - does NOT mock `backend.recognizers.product_recognizer.detectar_productos` (a `unittest.mock.patch` on that name is absent); the recognizer's real fuzzy logic and the resolver's real catalog-building code both run end-to-end;
  - sets `active_intent.candidate_ids` to the ids of the two pizza presentations only (NOT the third product); sets `active_intent.status = "pending_resolution"`; sets `active_intent.resolved_data = {"cantidad": 2}`;
  - calls `resolve_product_selection(db, "la grande", active_intent)`;
  - asserts the returned intent has `resolved_data["producto_presentacion_id"]` set to the "grande" presentation's `producto_presentacion_id`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids=[]`, the original `cantidad=2` preserved, and `status="ready"`.
- [ ] 2.3 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 363 tests. The unit-test subset uses a local SQLite in-memory database and may mock `detectar_productos`; the integration test does NOT touch `supernova_test` and does NOT mock the recognizer.
- [ ] 2.4 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.