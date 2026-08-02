## Why

Subphase 3.12 (per `openspec/specs/project.md` lines 910-980) introduces the per-context resolver for `PRODUCT_SELECTION`. The first attempt (`add-product-selection-context-resolver`) proposed a resolver that used prefixed field names (`producto_activo`, `producto_disponible`, `presentacion_activa`, `producto_presentacion_activa`) that do NOT match the names the existing `ProductRecognizer` (`backend/recognizers/product_recognizer.py`) reads. Implementing that proposal as-is would have left the recognizer's `producto_activo`, `presentacion_activo`, `activo`, `disponible` defaulted to `True` (the recognizer's `dict.get(key, True)` defaults), silently breaking the vendible check and any selection that depends on accurate availability. The subphase 3.12 spec explicitly forbids this: "Do not introduce alternate field names unless the recognizer already consumes them. Do not defer recognizer/catalog compatibility to a future subphase." This proposal reuses the exact field names the recognizer already reads.

## What Changes

- Add `backend/intents/context/product_selection_context_resolver.py` exporting one function `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` and a `__all__`.
- The function validates `active_intent.status == "pending_resolution"` and non-empty `active_intent.candidate_ids`; otherwise returns `active_intent` unchanged.
- The function queries the `producto_presentaciones` table restricted to the IDs in `active_intent.candidate_ids`, joins the related `productos`, `presentaciones`, and `categorias_productos` rows, and builds a catalog in the existing 12-field shape that `ProductRecognizer.detectar_productos` already reads (verified by reading `backend/recognizers/product_recognizer.py`).
- The function calls `detectar_productos(message, productos_presentaciones)` and returns a new `ProcessedIntent` with the selection applied when the recognizer returns exactly one item in `encontrados` AND the selected `producto_presentacion_id` is in the original `candidate_ids`; otherwise returns `active_intent` unchanged.
- The function is pure with respect to the resolver's own state: it does not commit, does not flush, does not close the session, does not call handlers, does not generate responses, does not modify the `Session` model. The caller owns the SQLAlchemy session and the commit.
- Add unit tests that may mock `detectar_productos` to assert catalog shape, call count, error cases, and `is` identity for the unchanged return. Add at least one real-integration test that calls the actual `backend.recognizers.product_recognizer.detectar_productos` (no mock) to verify the resolver-to-recognizer contract end-to-end with a restricted catalog and a user message such as `"la grande"`.

## Capabilities

### New Capabilities

- `product-selection-context-resolver`: The per-context function that resolves a pending `PRODUCT_SELECTION` by calling the existing `ProductRecognizer` with a candidate-restricted catalog. The future dispatch path will call this when the user replies with a disambiguating message.

### Modified Capabilities

- None. The active subphase is a thin wrapper that consumes the existing `ProductRecognizer` (subphase 3.11) as-is.

## Impact

- Adds `backend/intents/context/product_selection_context_resolver.py`.
- Adds unit tests + at least one real-integration test in `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no recognizer change, no handler, no persistence, no commit, no logging, no async.
- No new runtime dependencies. The function uses SQLAlchemy (already a project dependency) and the existing `detectar_productos` (subphase 3.11).

## Dependencies

- `detectar_productos` from `backend.recognizers.product_recognizer` (subphase 3.11).
- `ProcessedIntent` from `backend.intents.schemas.processed_intent` (subphase 3.3).
- `RequirementState` from `backend.intents.schemas.requirement_state` (subphase 3.2).
- `ProductoPresentacion`, `Producto`, `Presentacion`, `CategoriaProducto` from `backend.models.*` (Phase 1).
- `Session` (SQLAlchemy) and the `get_session` utility from `backend.dependencies`.

## Catalog Shape Confirmed from the Recognizer

The recognizer (`backend/recognizers/product_recognizer.py`) reads the catalog dict with these key accesses (verified at the time of this proposal):

- `producto_presentacion_id` (via `producto["producto_presentacion_id"]` in `_preparar_catalogo` and via `id` field)
- `producto_id` (via `producto["producto_id"]`)
- `presentacion_id` (via `producto["presentacion_id"]`)
- `categoria_id` (via `producto["categoria_id"]`)
- `producto_nombre` (via `producto["producto_nombre"]` and `nombre_original`)
- `categoria_nombre` (via `producto["categoria_nombre"]`)
- `presentacion_codigo` (via `producto["presentacion_codigo"]`)
- `presentacion_descripcion` (via `producto["presentacion_descripcion"]`)
- `producto_activo` (via `producto.get("producto_activo", True)` in the availability branch)
- `presentacion_activo` (via `producto.get("presentacion_activo", True)`)
- `activo` (via `producto.get("activo", True)` — the recognizer reads the flat `activo` field, which represents `producto_presentacion.activo` per the spec's mapping)
- `disponible` (via `producto.get("disponible", True)`)

This is the same 12-field shape the recognizer already consumes. The mapping from the DB rows to the recognizer's input fields is:
- DB `producto.activo` → catalog `producto_activo`
- DB `presentacion.activo` → catalog `presentacion_activo`
- DB `producto_presentacion.activo` → catalog `activo`
- DB `producto.disponible` → catalog `disponible`

## Incompatibility Found in the First Proposal

The first proposal (`add-product-selection-context-resolver`) used prefixed field names (`producto_activo`, `producto_disponible`, `presentacion_activa`, `producto_presentacion_activa`) that the recognizer does NOT read. Implementing that proposal would have left the recognizer's `producto_activo`/`presentacion_activo`/`activo`/`disponible` defaulted to `True`, silently making every item appear available. The subphase 3.12 spec explicitly forbids this. The current proposal reuses the recognizer's existing 12-field shape, so the implementation works correctly without a recognizer change.

## Artifacts Changed

This change creates the new change directory `openspec/changes/add-product-selection-context-resolver-3-12/` with four artifacts: `proposal.md`, `design.md`, `specs/product-selection-context-resolver-3-12/spec.md`, and `tasks.md`. The earlier two changes (`add-product-selection-context-resolver` and `add-product-selection-context-resolver-rework`) remain on disk for reference but are superseded by this one.