## Context

The legacy fuzzy pipeline at `backend/old_project/logica_fuzzy_pedido_productos.py` (891 lines) implements the product-matching logic. It works but has two structural problems the project must address before Phase 3's recognizer-adapter can land:

1. The recognizer imports `from backend.data.lista_json import productos as cat_prod_default` — a static JSON file. The future adapter subphase needs the recognizer to receive the catalog as an argument so it can fetch the catalog from the database.
2. The result is a JSON `str` with the legacy field names (`id`, `nombre_producto`, `tamanio`, `precio`, `disponible`). The future adapter needs the recognizer to return a Python `dict` with the new field names (`producto_presentacion_id`, `producto_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `categoria_id`, `categoria_nombre`, `activo`, `disponible`) so the `ProductIntentResolver` (subphase 3.5 in the Phase 3 roadmap) can consume it.

The active subphase ports the legacy pipeline to the new contract while preserving the fuzzy behavior. The legacy file is preserved in `backend/old_project/`; deleting it is a future cleanup.

## Goals / Non-Goals

**Goals:**

- Add `backend/recognizers/__init__.py` (empty package marker).
- Add `backend/recognizers/product_recognizer.py` exporting one function `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` and a `__all__`.
- The function preserves the legacy fuzzy pipeline (text normalization, quantity words, stopwords, product aliases, phonetic substitutions, prefix matching, segmentation, quantity extraction, presentation aliases, RapidFuzz scoring and thresholds) and applies it to the **new** catalog field names.
- The function does not query the database, does not depend on `backend.data.lista_json`, does not call repositories.
- The function returns a Python `dict` (not a JSON string) with exactly four keys: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`.
- Found products (`encontrados`) preserve the catalog fields and add `cantidad` and `texto_origen`.
- Possible products (`encontrados_posibles`) are grouped with `texto_origen` and a `productos` list.
- A product-presentation is unavailable when `activo is False` or `disponible is False`.
- The function preserves the legacy behavior for multiple products in one message.
- The function uses `producto_presentacion_id` as the unique candidate identifier.
- The function is importable without side effects.
- One test covers: unique match, same product with multiple presentations, explicit presentation, unavailable product, unknown product, multiple products and quantities, restricted catalog.

**Non-Goals:**

- No model, no migration, no router, no FastAPI endpoint, no persistence, no DB query, no logging, no `print`/debug.
- No new fuzzy logic. The active subphase preserves the legacy behavior; the future cleanup may add scoring tweaks.
- No `backend/data/lista_json.py` restoration. The active subphase does not depend on the legacy JSON file.
- No recognizer-adapter (the wrapper that calls `detectar_productos` and pipes the output into `ProductIntentResolver`). That lands in a future subphase.
- No deletion of `backend/old_project/logica_fuzzy_pedido_productos.py`. The active subphase preserves the legacy file; a future cleanup removes it.
- No async.

## Decisions

- **D1 — Function returns a Python `dict`, not a JSON string.** The spec mandates this. The future adapter (Phase 3's recognizer-adapter subphase) will convert the dict to JSON if needed; today the recognizer is a pure function.
- **D2 — Field-name mapping from legacy to new.** Confirmed by reading `backend/old_project/lista_json.py` (52 items, each with the 8 legacy fields `id`, `idcategoria`, `nombre_producto`, `nombre_categoria`, `tamanio`, `precio`, `disponible`):
  - `id` → `producto_presentacion_id` (the unique candidate identifier)
  - `nombre_producto` → `producto_nombre` (the product name, matched against `texto`)
  - `tamanio` → `presentacion_codigo` (the presentation code/label). Legacy `tamanio` values are short codes (`"chica"`, `"grande"`, `"unidad"`, `"lata"`, `"1 litro"`) used by the legacy match logic to tokenize user text; they fit the `presentacion_codigo` field semantically. `presentacion_descripcion` is left empty for legacy data.
  - `precio` → dropped (the new schema does not surface price in the recognizer; the future handler reads it from the DB)
  - `disponible` → kept. A product-presentation is unavailable when `disponible is False`.
  - `idcategoria` → `categoria_id`
  - `nombre_categoria` → `categoria_nombre`
  - The new schema adds `producto_id`, `presentacion_id`, `activo`. The recognizer passes them through to the output dict; it does not use them for matching. `producto_id` and `presentacion_id` MUST be present in the input (the caller is responsible for converting from the DB model). `activo` defaults to `True` when missing (legacy data has no `activo`; the absence implies "active by default").
- **D3 — Match is against `producto_nombre` first, then `presentacion_codigo` / `presentacion_descripcion`.** This mirrors the legacy behavior (product name match; if a presentation-specific token is in the user text, restrict to that presentation). A future subphase may invert the priority; today the legacy behavior is preserved.
- **D4 — `encontrados_posibles` groups all valid presentations of a single matched product under one `texto_origen`.** A user text like "pizza" with two valid presentations produces ONE group with `productos: [pres_a, pres_b]`, not two separate groups. The future resolver iterates the `productos` list and asks the user to pick.
- **D5 — The function uses `producto_presentacion_id` as the unique candidate identifier.** The output dict's `encontrados` and `encontrados_posibles` entries reference the same id field. The future handler uses this id to dispatch the action.
- **D6 — The function does not introduce new fuzzy logic.** The active subphase preserves the legacy scoring (`calcular_score`), segmentation (`segmentar_pedido`), and fragment extraction (`extraer_fragmentos_candidatos`). A future cleanup subphase may add Levenshtein-windowing, tokenizer, or scoring tweaks; the active subphase is a behavior-preserving port.
- **D7 — `__all__` declares one public symbol.** `detectar_productos`. Mirrors the prior subphases' `__all__` discipline.
- **D8 — File location: `backend/recognizers/product_recognizer.py`.** The `backend/recognizers/` package is the new home for the intent-recognition layer. Future recognizers (`cerrar_pedido_recognizer`, etc.) slot in alongside. Mirrors the `backend/intents/{contracts,schemas,services}/` layout.
- **D9 — No `__all__` for the legacy file.** The active subphase does not modify the legacy `backend/old_project/logica_fuzzy_pedido_productos.py`. The future cleanup may re-export its constants from the new module; today the legacy file is untouched.

## Risks / Trade-offs

- **[Risk] The legacy fuzzy pipeline has 891 lines; the new module is a near-verbatim port.** → Acceptable: the active subphase's goal is behavior preservation. A future subphase can refactor / split the module.
- **[Risk] `presentacion_codigo` and `presentacion_descripcion` are concatenated for the match.** The spec says "Perform presentation matching against `presentacion_codigo` and `presentacion_descripcion`" — the match is the union of both fields. A user text containing "familiar" matches a presentation whose `presentacion_codigo == "familiar"`.
- **[Trade-off] The module returns a Python `dict`; future consumers may need JSON.** → The future adapter (Phase 3's recognizer-adapter subphase) calls `json.dumps(...)` on the dict if needed. The recognizer stays pure.
- **[Trade-off] The legacy file remains in `backend/old_project/`.** A future cleanup deletes it. Today the file is preserved as the reference implementation.

## Open Questions

- None. The function signature, the field-name mapping, the return shape, and the "no DB / no `lista_json`" rule are all fixed by Subphase 3.11 in `project.md`.