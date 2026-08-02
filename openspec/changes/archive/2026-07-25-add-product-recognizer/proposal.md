## Why

The legacy fuzzy pipeline (`backend/old_project/logica_fuzzy_pedido_productos.py`) implements the product-matching logic in 891 lines. It works but has two problems the project must address before Phase 3's recognizer-adapter can land:

1. The recognizer reads the product catalog from `backend.data.lista_json` (a static JSON file). The future adapter subphase needs the recognizer to receive the catalog as an argument so it can fetch the catalog from the database.
2. The result is a JSON string with the legacy field names (`id`, `nombre_producto`, `tamanio`, `precio`, `disponible`). The future adapter (subphase 3.5+ in the spec roadmap) needs the recognizer to return a Python `dict` with the new field names (`producto_presentacion_id`, `producto_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `categoria_id`, `categoria_nombre`, `activo`, `disponible`) so the `ProductIntentResolver` can consume it.

Without a clean product-recognizer module the dispatch path cannot land. This subphase ports the legacy pipeline to the new contract while preserving the fuzzy behavior (text normalization, quantity words, stopwords, product aliases, phonetic substitutions, prefix matching, segmentation, quantity extraction, presentation aliases, RapidFuzz scoring and thresholds).

## What Changes

- Add `backend/recognizers/__init__.py` (empty package marker).
- Add `backend/recognizers/product_recognizer.py` exporting a single function `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` and a `__all__`.
- The function preserves the legacy fuzzy pipeline (text normalization, quantity words, stopwords, product aliases, phonetic substitutions, prefix matching, segmentation, quantity extraction, presentation aliases, RapidFuzz scoring and thresholds) and applies it to the **new** catalog field names.
- The function receives the full or restricted catalog as an argument. The caller (a future adapter subphase) is responsible for fetching the catalog from the database AND for converting from the database model shape to the recognizer's input shape.
- The function does **not** query the database, **not** depend on `backend.data.lista_json`, **not** call repositories.
- The function returns a Python `dict` (not a JSON string) with exactly four keys: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`.
- Found products (`encontrados`) preserve the catalog fields and add `cantidad` and `texto_origen`.
- Possible products (`encontrados_posibles`) are grouped with `texto_origen` and a `productos` list.
- A product-presentation is unavailable when `activo is False` or `disponible is False`.
- The function preserves the legacy behavior for multiple products in one message.
- Add one test entry to `backend/tests/api_smoke.py` covering: unique match, same product with multiple presentations, explicit presentation, unavailable product, unknown product, multiple products and quantities, restricted catalog.

## Capabilities

### New Capabilities

- `product-recognizer`: The fuzzy product-matching module that takes free-text user input and a catalog of product-presentations, and returns a structured dict of confident matches, possible matches, unavailable matches, and unmatched fragments.

### Modified Capabilities

- None. The legacy `backend/old_project/logica_fuzzy_pedido_productos.py` is preserved in place; the new module is a clean re-implementation. The active subphase does not delete the legacy file; that lands in a future cleanup subphase.

## Impact

- Adds `backend/recognizers/__init__.py` and `backend/recognizers/product_recognizer.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no persistence. The function is pure (plus a small `RapidFuzz` import for fuzzy scoring).
- No new runtime dependencies beyond what the legacy module already uses (`rapidfuzz`, `re`, `unicodedata`).

## Dependencies

- `rapidfuzz.fuzz`, `re`, `unicodedata` (standard library + already-installed dependency).
- The catalog item shape (per the spec): `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`. A future subphase will provide a fixture or a small DB-driven helper that produces this shape.
- The legacy `backend/old_project/logica_fuzzy_pedido_productos.py` is the reference implementation. The active subphase preserves the same fuzzy behavior; no new fuzzy logic.
- Field-mapping conventions derived from the legacy `lista_json.py` (52 items, 8 fields each: `id`, `idcategoria`, `nombre_producto`, `nombre_categoria`, `tamanio`, `precio`, `disponible`):
  - Legacy `tamanio` values are short codes/labels (`"chica"`, `"grande"`, `"unidad"`, `"lata"`, `"1 litro"`) used by the legacy match logic to tokenize user text. These map to the new `presentacion_codigo`. The new `presentacion_descripcion` is left empty for legacy data (the caller may populate it from a richer DB field in a future subphase).
  - Legacy `disponible` carries the "unavailable" semantics: the legacy `encontrados_no_disponibles` is populated when `disponible is False`. The new schema adds `activo` as an additional unavailability signal; the active subphase treats `activo` as `True` when missing (the catalog input is the live catalog of products the system offers).
  - Legacy `precio` is dropped from the recognizer's output (the future handler reads price from the DB; the recognizer does not surface it).