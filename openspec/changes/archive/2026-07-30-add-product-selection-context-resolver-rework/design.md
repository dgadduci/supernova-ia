## Context

The previous `add-product-selection-context-resolver` change proposed a per-context resolver for `PRODUCT_SELECTION` but used new prefixed field names (`producto_activo`, `producto_disponible`, `presentacion_activa`, `producto_presentacion_activa`) that do NOT match the names the existing `ProductRecognizer` (subphase 3.11) reads. Implementing the previous proposal as-is would leave the recognizer's `producto_activo`, `presentacion_activo`, `activo`, and `disponible` defaulted to `True`, silently breaking the vendible check. This rework proposes a resolver whose catalog field names exactly match the recognizer's existing input contract, so the implementation works correctly without requiring a recognizer change.

The existing `ProductRecognizer` (`backend/recognizers/product_recognizer.py`) reads the catalog as a list of dicts with these fields: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `producto_activo`, `presentacion_activo`, `activo` (representing `producto_presentacion.activo`), and `disponible` (representing `producto.disponible`). The rework builds the catalog in this exact shape.

## Goals / Non-Goals

**Goals:**

- Create `backend/intents/context/product_selection_context_resolver.py` exporting one function `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` and a `__all__`.
- The function validates `active_intent.status == "pending_resolution"` and non-empty `active_intent.candidate_ids`; otherwise returns `active_intent` unchanged.
- The function queries the `producto_presentaciones` table restricted to the IDs in `active_intent.candidate_ids`, joins the related `productos`, `presentaciones`, and `categorias_productos` rows, and builds a catalog in the existing 12-field shape that `detectar_productos` reads.
- The function calls `detectar_productos(message, productos_presentaciones)` and returns a new `ProcessedIntent` with the selection applied when the recognizer returns exactly one item in `encontrados` AND the selected `producto_presentacion_id` is in the original `candidate_ids`; otherwise returns `active_intent` unchanged.
- The function is **pure with respect to the resolver's own state**: it does not commit, does not flush, does not close the session, does not call handlers, does not generate responses, does not modify the `Session` model. The caller owns the SQLAlchemy session and the commit.
- The function is importable without side effects.
- One test covers: unique selection by presentation, query restricted to `candidate_ids`, original `cantidad` preserved, ambiguous result unchanged, unavailable/unknown result unchanged, selected-id-outside-original-candidates rejected, fully resolved intent becomes `ready`.

**Non-Goals:**

- No model, no migration, no router, no FastAPI endpoint, no recognizer change, no handler, no persistence, no commit, no logging, no async.
- No modifications to the existing `ProductRecognizer` (subphase 3.11). The active subphase consumes the recognizer as-is.
- No field-name translation. The active subphase builds the catalog in the shape the recognizer reads.
- No additional per-context resolvers (e.g. `cerrar_pedido_resolver`). One resolver per subphase.

## Decisions

- **D1 — The resolver takes a `db: Session` parameter (a SQLAlchemy session) explicitly.** The spec mandates this. The function uses the `db` to query `producto_presentaciones` restricted to `active_intent.candidate_ids`. The caller (a future dispatch subphase) is responsible for the session lifecycle and the commit.
- **D2 — The function queries `producto_presentaciones` with `where(id.in_(candidate_ids))`** and uses `joinedload` to load `producto`, `producto.categoria`, and `presentacion` in a single round-trip. N+1 is avoided.
- **D3 — The function builds the catalog in the recognizer's existing 12-field shape:**
  `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `producto_activo` (bool(pp.producto.activo)), `presentacion_activo` (bool(pp.presentacion.activo)), `activo` (bool(pp.activo), representing `producto_presentacion.activo`), `disponible` (bool(pp.producto.disponible), representing `producto.disponible`).
  The mapping from the DB rows to the recognizer's input fields is:
  - DB `producto.activo` → `producto_activo`
  - DB `presentacion.activo` → `presentacion_activo`
  - DB `producto_presentacion.activo` → `activo`
  - DB `producto.disponible` → `disponible`
- **D4 — The function returns `active_intent` unchanged in every failure case.** Ambiguous selection, unavailable product, not-found product, empty candidate list, selected-id outside the original `candidate_ids`, missing `pending_resolution` status — all return the input unchanged. The caller is responsible for handling the "no resolution" case.
- **D5 — The function preserves the original `resolved_data` (including `cantidad`)** when applying the selection. The selected `producto_presentacion_id` is added to `resolved_data` without overwriting other keys.
- **D6 — The function sets `status="ready"` only when no required requirement remains pending.** The same vendible logic the recognizer uses, applied to the requirements list. If `cantidad` is still pending (e.g. the user selected a product but did not specify quantity), the status stays `"pending_resolution"`.
- **D7 — The function is the per-context bridge between the recognizer and the future handler.** The future handler consumes a `ready` `ProcessedIntent` (with `producto_presentacion_id` set and `candidate_ids` cleared) and dispatches the action via `pedido_producto`. The active subphase does not introduce that handler.
- **D8 — `__all__` declares one public symbol.** `resolve_product_selection`. Mirrors the prior subphases' `__all__` discipline.
- **D9 — Tests use a local SQLite in-memory database** (not the project's `supernova_test`) to keep the test isolated. The function is tested with a real SQLAlchemy session against a `Base.metadata.create_all(engine)`-created in-memory DB. Sample `ProductoPresentacion` rows joined to `Producto`, `Presentacion`, `CategoriaProducto` are inserted; the resolver queries these and runs the recognizer. Unit tests may mock `detectar_productos` to assert the catalog shape and call count; the active subphase ALSO requires a separate real-integration test that calls the actual `backend.recognizers.product_recognizer.detectar_productos` (no mock) to verify the resolver-to-recognizer contract end-to-end.

## Risks / Trade-offs

- **[Risk] The resolver depends on the existing recognizer's field-name contract.** If a future subphase updates the recognizer to use different field names, this resolver must be updated to match. → Acceptable: the rework is a thin wrapper that delegates to the recognizer; a contract change on the recognizer side requires a corresponding change here.
- **[Risk] Empty candidate list short-circuits to `active_intent` unchanged.** Acceptable: the spec mandates this; a candidate list of 0 means there is nothing to match against.
- **[Trade-off] The function does not validate the user's `message` against the original `source_text`.** Acceptable: the recognizer's fuzzy logic handles arbitrary messages; the future dispatch path is responsible for re-validating that the user is in the right state.
- **[Trade-off] The function returns a new `ProcessedIntent` on success, not a copy with a mutation.** The input `active_intent` is unchanged (the function never mutates it). Tests assert `is` identity for the unchanged case.

## Open Questions

- None. The function signature, the validation rules, the field-name map (matching the recognizer's existing input contract), the "do not modify session / persist / commit / execute handlers" rule, and the requirement to include a real-integration test against `backend.recognizers.product_recognizer.detectar_productos` are all fixed by the spec.