## Context

Phase 3 (Intents) is layering up the dispatch path. The `intents.context` package already hosts `context_type_resolver.py` (subphase 3.9) and `pending_context_service.py` (subphase 3.10), both pure functions that operate on a `Session` model instance. Subphase 3.11 introduced the pure `ProductRecognizer` (`detectar_productos`) that takes a catalog of product-presentations and returns a structured dict. The `ProductSelectionContextResolver` is the per-context function that resolves a pending `PRODUCT_SELECTION` flow: it takes the user's selection reply and the active `ProcessedIntent`, queries the DB for the candidate products, runs the recognizer with a candidate-restricted catalog, and returns a new `ProcessedIntent` with the chosen product's id (or the input unchanged on failure).

The active subphase is the third attempt at this resolver. The first (`add-product-selection-context-resolver`) used field names that the recognizer did not consume, which would have silently broken availability checks. The second (`add-product-selection-context-resolver-rework`) corrected the field names to match the recognizer's existing 12-field input contract. This proposal is the final subphase 3.12 proposal that reuses the recognizer's existing field names, follows the subphase 3.12 spec in `project.md` (lines 910-980), and includes a real-integration test with the actual recognizer.

## Goals / Non-Goals

**Goals:**

- Create `backend/intents/context/product_selection_context_resolver.py` exporting one function `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` and a `__all__`.
- The function validates `active_intent.status == "pending_resolution"` and non-empty `active_intent.candidate_ids`; otherwise returns `active_intent` unchanged.
- The function queries the `producto_presentaciones` table restricted to the IDs in `active_intent.candidate_ids`, joins the related `productos`, `presentaciones`, and `categorias_productos` rows, and builds a catalog in the existing 12-field shape that `detectar_productos` reads.
- The function calls `detectar_productos(message, productos_presentaciones)` and returns a new `ProcessedIntent` with the selection applied when the recognizer returns exactly one item in `encontrados` AND the selected `producto_presentacion_id` is in the original `candidate_ids`; otherwise returns `active_intent` unchanged.
- The function is pure with respect to the resolver's own state: it does not commit, does not flush, does not close the session, does not call handlers, does not generate responses, does not modify the `Session` model. The caller owns the SQLAlchemy session and the commit.
- The function is importable without side effects.
- Unit tests cover: unique selection by presentation, query restricted to `candidate_ids`, original quantity preserved, ambiguous result unchanged, unavailable/unknown result unchanged, selected-id outside original `candidate_ids` rejected, fully resolved intent becomes `ready`.
- At least one real-integration test must use the actual `backend.recognizers.product_recognizer.detectar_productos` (no mock) to verify the resolver-to-recognizer contract end-to-end with a restricted catalog and a user message such as `"la grande"`.

**Non-Goals:**

- No model, no migration, no router, no FastAPI endpoint, no recognizer change, no handler, no persistence, no commit, no logging, no async.
- No modifications to the existing `ProductRecognizer` (subphase 3.11). The active subphase consumes the recognizer as-is.
- No field-name translation. The active subphase builds the catalog in the shape the recognizer reads.
- No additional per-context resolvers (e.g. `cerrar_pedido_resolver`). One resolver per subphase.

## Decisions

- **D1 — The resolver takes a `db: Session` parameter (a SQLAlchemy session) explicitly.** The spec mandates this. The function uses the `db` to query `producto_presentaciones` restricted to `active_intent.candidate_ids`. The caller (a future dispatch subphase) is responsible for the session lifecycle and the commit.
- **D2 — The function queries `producto_presentaciones` with `where(id.in_(candidate_ids))`** and uses `joinedload` to load `producto`, `producto.categoria`, and `presentacion` in a single round-trip. N+1 is avoided.
- **D3 — The function builds the catalog in the recognizer's existing 12-field shape** (verified by reading `backend/recognizers/product_recognizer.py`):
  - `producto_presentacion_id`: `pp.id`
  - `producto_id`: `pp.id_producto`
  - `presentacion_id`: `pp.id_presentacion`
  - `categoria_id`: `pp.producto.id_categoria_producto`
  - `producto_nombre`: `pp.producto.nombre`
  - `categoria_nombre`: `pp.producto.categoria.descripcion`
  - `presentacion_codigo`: `pp.presentacion.codigo`
  - `presentacion_descripcion`: `pp.presentacion.descripcion`
  - `producto_activo`: `bool(pp.producto.activo)`
  - `presentacion_activo`: `bool(pp.presentacion.activo)`
  - `activo`: `bool(pp.activo)` (representing `producto_presentacion.activo`)
  - `disponible`: `bool(pp.producto.disponible)` (representing `producto.disponible`)
  This shape exactly matches the existing recognizer's input contract; no new field names are introduced.
- **D4 — The function returns `active_intent` unchanged in every failure case.** Ambiguous selection, unavailable product, not-found product, empty candidate list, selected-id outside the original `candidate_ids`, missing `pending_resolution` status — all return the input unchanged (same instance, `is` comparison). The caller is responsible for handling the "no resolution" case.
- **D5 — The function preserves the original `resolved_data` (including `cantidad`)** when applying the selection. The selected `producto_presentacion_id` is added to `resolved_data` without overwriting other keys.
- **D6 — The function sets `status="ready"` only when no required requirement remains pending.** The same vendible logic the recognizer uses, applied to the requirements list. If `cantidad` is still pending (e.g. the user selected a product but did not specify quantity), the status stays `"pending_resolution"`.
- **D7 — The function is the per-context bridge between the recognizer and the future handler.** The future handler consumes a `ready` `ProcessedIntent` (with `producto_presentacion_id` set and `candidate_ids` cleared) and dispatches the action via `pedido_producto`. The active subphase does not introduce that handler.
- **D8 — `__all__` declares one public symbol.** `resolve_product_selection`. Mirrors the prior subphases' `__all__` discipline.
- **D9 — Tests split into two groups:** (a) unit tests that may mock `detectar_productos` to assert the catalog shape, call count, error cases, and `is` identity for the unchanged return; (b) at least one real-integration test that calls the actual `backend.recognizers.product_recognizer.detectar_productos` (no mock) to verify the resolver-to-recognizer contract end-to-end. The unit tests use a local SQLite in-memory database; the integration test also uses a local SQLite in-memory database (NOT the project's `supernova_test`).

## Risks / Trade-offs

- **[Risk] The resolver depends on the existing recognizer's field-name contract.** If a future subphase updates the recognizer to use different field names, this resolver must be updated to match. → Acceptable: the active subphase is a thin wrapper that delegates to the recognizer; a contract change on the recognizer side requires a corresponding change here.
- **[Risk] Empty candidate list short-circuits to `active_intent` unchanged.** Acceptable: the spec mandates this; a candidate list of 0 means there is nothing to match against.
- **[Trade-off] The function does not validate the user's `message` against the original `source_text`.** Acceptable: the recognizer's fuzzy logic handles arbitrary messages; the future dispatch path is responsible for re-validating that the user is in the right state.
- **[Trade-off] The function returns a new `ProcessedIntent` on success, not a copy with a mutation.** The input `active_intent` is unchanged (the function never mutates it). Tests assert `is` identity for the unchanged case.

## Open Questions

- None. The function signature, the validation rules, the field-name map (matching the recognizer's existing input contract), the "do not modify session / persist / commit / execute handlers" rule, and the requirement to include a real-integration test against `backend.recognizers.product_recognizer.detectar_productos` are all fixed by the subphase 3.12 spec.