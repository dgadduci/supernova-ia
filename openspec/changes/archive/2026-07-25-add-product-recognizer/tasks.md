## 1. Recognizer Module

- [x] 1.1 Create the empty package marker `backend/recognizers/__init__.py`.
- [x] 1.2 Create `backend/recognizers/product_recognizer.py` exporting one function:
  - `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` — pure fuzzy recognizer, no DB, no `lista_json` import, no `print`/logging.
  - Re-use the legacy fuzzy pipeline from `backend/old_project/logica_fuzzy_pedido_productos.py` as a reference: `STOPWORDS`, `PALABRAS_CANTIDAD`, `TAMANIOS`, `ALIASES_PALABRAS`, `_FONETICA`, `normalizar_texto`, `normalizar_fonetico`, `normalizar_palabras_pedido`, `_score_prefijo_token`, `score_prefijo_fragmento`, `calcular_score`, `extraer_fragmentos_candidatos`, `segmentar_pedido`, `CATEGORIAS_PRODUCTO`. Re-implement these (or import from the legacy module) but apply the **new** field-name mapping (verified against `backend/old_project/lista_json.py`):
    - legacy `id` → `producto_presentacion_id` (the unique candidate identifier)
    - legacy `idcategoria` → `categoria_id`
    - legacy `nombre_producto` → `producto_nombre`
    - legacy `nombre_categoria` → `categoria_nombre`
    - legacy `tamanio` → `presentacion_codigo` (legacy `tamanio` values are short codes/labels like `"chica"`, `"grande"`, `"unidad"`, `"lata"`, `"1 litro"`)
    - legacy `precio` → DROPPED (not in the input catalog; the future handler reads price from the DB)
    - legacy `disponible` → `disponible` (kept; `disponible=False` is the "unavailable" signal in the legacy data)
  - The function's input catalog uses the spec's shape: each item MUST have `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`. The caller is responsible for converting from the DB model to this shape.
  - `presentacion_descripcion` may be empty (legacy data has it empty; the field is reserved for future richer data).
  - `activo` defaults to `True` when the field is missing or not provided (legacy data has no `activo`; absence implies "active").
  - Filter candidates where `producto_presentacion_id` is missing or falsy (skip). Match is against `producto_nombre`; if a presentation token (substring of `presentacion_codigo` or `presentacion_descripcion`) appears in the user text, restrict to that presentation.
  - A product-presentation is unavailable when `activo is False` OR `disponible is False`; place it in `encontrados_no_disponibles`, not in `encontrados`.
  - One fragment matches multiple valid presentations of the same product → ONE entry in `encontrados_posibles` with `{"texto_origen": <fragment>, "productos": [<pres_a>, <pres_b>]}`.
  - Each entry in `encontrados` preserves every catalog field and adds `cantidad` (int) and `texto_origen` (str).
  - Each entry in `encontrados_posibles` has the `texto_origen` and `productos` list of catalog items (without `cantidad`).
  - Each entry in `encontrados_no_disponibles` has the `texto_origen` and a single `producto` (or `productos`) catalog item that is unavailable.
  - The return value is a Python `dict` (NOT a JSON string) with exactly four keys: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`.
  - Declare `__all__ = ["detectar_productos"]`.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `detectar_productos`;
  - asserts the function is importable and the only public symbol is `detectar_productos`;
  - asserts the function does NOT import `lista_json`, `sqlalchemy`, or any repository module (grep the source);
  - asserts unique product match (`pizza muzza`) populates `encontrados` with one item preserving every catalog field plus `cantidad` and `texto_origen`;
  - asserts the same product with two presentations (chica + grande) and text "pizza" populates `encontrados_posibles` with one group whose `productos` list contains both;
  - asserts explicit presentation in text (e.g. "pizza familiar") picks the matching presentation as the only `encontrados` entry;
  - asserts `disponible=False` populates `encontrados_no_disponibles` and NOT `encontrados`;
  - asserts `activo=False` populates `encontrados_no_disponibles` and NOT `encontrados`;
  - asserts `activo` absent (legacy shape) with `disponible=True` populates `encontrados` (the absence of `activo` is interpreted as `True`);
  - asserts `presentacion_descripcion` empty (legacy data, mapped from `tamanio`) still allows presentation matching against `presentacion_codigo`;
  - asserts unknown product populates `no_encontrados` and leaves `encontrados` empty;
  - asserts multiple products in one message ("2 pizzas muzza y 1 empanada") populates `encontrados` with both items and correct `cantidad` values;
  - asserts restricted catalog (a text matches a product name but the product is NOT in the supplied list) populates `no_encontrados` and NOT `encontrados`;
  - asserts the result type is `dict` (NOT `str`); asserts the four keys are present;
  - asserts the module's `__all__` is exactly `{"detectar_productos"}`;
  - asserts `backend/recognizers/` contains only `__init__.py` and `product_recognizer.py`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 339 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.