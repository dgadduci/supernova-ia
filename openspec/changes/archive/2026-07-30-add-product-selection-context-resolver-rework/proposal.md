## Why

The previous `add-product-selection-context-resolver` change proposed a resolver that used new prefixed field names (`producto_activo`, `producto_disponible`, `presentacion_activa`, `producto_presentacion_activa`) that do NOT match the names the existing `ProductRecognizer` (subphase 3.11) reads. Implementing the previous proposal as-is would cause the resolver to populate fields the recognizer ignores and leave the recognizer's expected fields empty (defaulted to `True`), breaking the vendible check and any future selection that depends on accurate availability. This rework proposes a resolver whose catalog field names exactly match the recognizer's existing input contract, so the implementation works correctly without requiring a recognizer change.

## What Changes

- Add `backend/intents/context/product_selection_context_resolver.py` exporting one function `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` and a `__all__`.
- The function validates `active_intent.status == "pending_resolution"` and non-empty `active_intent.candidate_ids`; otherwise returns `active_intent` unchanged.
- The function queries the `producto_presentaciones` table restricted to the IDs in `active_intent.candidate_ids`, joins the related `productos`, `presentaciones`, and `categorias_productos` rows, and builds a catalog in the field shape that `ProductRecognizer.detectar_productos` reads.
- The function calls `detectar_productos(message, productos_presentaciones)` and returns a new `ProcessedIntent` with the selection applied when the recognizer returns exactly one item in `encontrados` AND the selected `producto_presentacion_id` is in the original `candidate_ids`; otherwise returns `active_intent` unchanged.
- The function is pure with respect to the resolver's own state: it does not commit, does not flush, does not close the session, does not call handlers, does not generate responses. The caller owns the SQLAlchemy session and the commit.
- Add one test entry to `backend/tests/api_smoke.py` covering: unique selection by presentation, query restricted to `candidate_ids`, original `cantidad` preserved, ambiguous result unchanged, unavailable/unknown result unchanged, selected-id-outside-original-candidates rejected, fully resolved intent becomes `ready`.

## Capabilities

### New Capabilities

- `product-selection-context-resolver`: The per-context function that resolves a pending `PRODUCT_SELECTION` by calling the existing `ProductRecognizer` with a candidate-restricted catalog. The future dispatch path will call this when the user replies with a disambiguating message.

### Modified Capabilities

- None. The active subphase is a correction to the previous `add-product-selection-context-resolver` proposal that was never implemented. The existing `ProductRecognizer` is unchanged.

## Impact

- Adds `backend/intents/context/product_selection_context_resolver.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no recognizer change, no handler, no persistence. The function reads from the DB and calls the existing recognizer; the caller is responsible for the SQLAlchemy session and the commit.
- No new runtime dependencies. The function uses SQLAlchemy (already a project dependency) and the existing `detectar_productos` (subphase 3.11).

## Dependencies

- `detectar_productos` from `backend.recognizers.product_recognizer` (subphase 3.11).
- `ProcessedIntent` from `backend.intents.schemas.processed_intent` (subphase 3.3).
- `RequirementState` from `backend.intents.schemas.requirement_state` (subphase 3.2).
- `ProductoPresentacion`, `Producto`, `Presentacion`, `CategoriaProducto` from `backend.models.*` (Phase 1).
- `Session` (SQLAlchemy) and the `get_session` utility from `backend.dependencies`.