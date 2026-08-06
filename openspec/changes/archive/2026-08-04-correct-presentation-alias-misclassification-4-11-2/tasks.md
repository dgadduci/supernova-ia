## 1. Roadmap and Classification Review

- [x] 1.1 Replace the pending Subphase 4.11.2 implementation prompt in `openspec/specs/project.md` with the roadmap entry “Subphase 4.11.2 — Correct Presentation Alias Misclassification in Product Recognition” and its objective to prevent product descriptors from filtering valid candidates.
- [x] 1.2 Inspect `PRESENTACION_ALIASES`, `_extraer_presentacion`, presentation candidate filtering, current catalog presentation values, and the real modificar-producto flow; record which aliases are genuine presentations and which are clearly product descriptors.

  **Inspection findings (recorded for traceability):**
  - Catalog `presentaciones` codes for every `comercio_id` are: `CHICA`, `GRANDE`, `LATA`, `LITRO`, `LITRO_MEDIO`, `PORCION`, `UNIDAD`, `DOS_LITROS`, `KILO`. `picante` and `tradicional` are NOT present.
  - `picante` is part of `producto_nombre` only (e.g., `Empanada de Carne Picante`); it is a flavor/variant in product identity, never a presentation. **Clearly a product descriptor — must be removed.**
  - `tradicional` does not appear in any `producto_nombre`, `producto_aliases.alias`, or `presentacion.codigo`/`descripcion`. The same classification error is not currently demonstrated by catalog evidence, so the alias is preserved per the design decision (minimal change, conservative review).
  - All other aliases (`chica`, `mediana`, `grande`, `unidad`, `lata`, `litro`, `litros`, `medio`, `gran`, `grandi`, `chico`, `chiqui`, `pequena`, `pequeno`, `familiar`, `fami`, `individual`, `porción`, `docena`) map to actual catalog presentation codes; they remain intact, no fuzzy scores, thresholds, ranking, or output shape change.

## 2. Minimal Recognizer Correction

- [x] 2.1 Remove `picante` from `PRESENTACION_ALIASES` in `backend/recognizers/product_recognizer.py` so it remains part of product identity and does not activate structured presentation filtering.
- [x] 2.2 Change any adjacent presentation alias only if current catalog evidence proves the same classification error; otherwise preserve the existing aliases and avoid recognizer redesign.

  Reviewed `tradicional` (the only other possibly descriptor-like alias). Catalog evidence shows it does not appear in any `producto_nombre`, `producto_aliases`, or `presentacion.codigo`/`descripcion`. The conservative review decision is to **preserve** `tradicional`; the same misclassification is not currently demonstrated.
- [x] 2.3 Confirm legitimate presentation handling remains intact for `chica`, `mediana`, `grande`, `unidad`, `porción`, `docena`, `media docena`, `litro`, and `medio litro` without changing fuzzy scores, thresholds, ranking, or output shape.

  No changes to `_extraer_presentacion`, `_calcular_score`, `_extraer_candidatos`, presentation filter logic, or output shape. Aliases for `chica/chico/chiqui/familiar/fami/individual/unidad/lata/litro/litros/medio/gran/grandi/pequena/pequeno/tradicional` are unchanged. Fuzzy scores, thresholds, ranking, and output shape are untouched.

## 3. Regression Coverage and Settings Fixture

- [x] 3.1 Add focused product recognizer tests proving `empanadas carne picante` resolves the expected `unidad` destination and is not discarded by a fake presentation mismatch.
- [x] 3.2 Add focused tests proving legitimate presentation terms still filter the correct candidate and unknown terms do not create false product matches.
- [x] 3.3 Ensure `backend/tests/test_modificar_producto_real_flow_http.py::ModificarProductoRealFlowHttpTest::test_defect_1_full_transfer_on_omitted_quantity` succeeds with the full source quantity transferred to the descriptor-bearing destination.
- [x] 3.4 Ensure `backend/tests/test_modificar_producto_real_flow_http.py::ModificarProductoRealFlowHttpTest::test_defect_2_unknown_destination_preserves_source` continues rejecting an unknown destination without mutating the source.
- [x] 3.5 Change the `EMBEDDING_MODEL` override and assertion in `backend/tests/test_llm_settings.py` to the synthetic value `test-embedding-model`, preserving the environment-override test purpose and production defaults.

## 4. Verification

- [x] 4.1 Run `PYTHONPATH=. venv/bin/pytest backend/tests/test_modificar_producto_real_flow_http.py::ModificarProductoRealFlowHttpTest::test_defect_1_full_transfer_on_omitted_quantity backend/tests/test_modificar_producto_real_flow_http.py::ModificarProductoRealFlowHttpTest::test_defect_2_unknown_destination_preserves_source backend/tests/test_llm_settings.py -vv`. → **14/14 passed** (2 real-flow defects + 12 LLM settings tests).
- [x] 4.2 Run the focused product recognizer regressions in `backend/tests/test_product_recognizer.py`, plus any additional recognizer test file changed by this subphase. → **12/12 passed** (5 pre-existing stopword tests + 7 new presentation tests).
- [x] 4.3 Run `PYTHONPATH=. venv/bin/python -m ruff check` over every touched Python file and fix only failures introduced by this change. → `product_recognizer.py` and `test_product_recognizer.py` clean (one import sort I001 fixed). `test_llm_settings.py` carries 3 pre-existing B017 errors at lines 28/120/122 (blind `Exception` assertions, untouched by this change and out of scope per the "fix only failures introduced by this change" rule).
- [x] 4.4 Run `PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py` and report any pre-existing unrelated failures separately. → 16 pre-existing errors, all `Missing type arguments for generic type "dict"` / `"tuple"` at lines 71/244/341/342/404/408/416/426/503/504/507/532/533/562/565/566. Confirmed pre-existing by `git stash` + same 16 errors on `main`. None of them are on the line I touched (the deleted `picante` line).
- [x] 4.5 Run `PYTHONPATH=. venv/bin/python -m compileall` over every touched Python file and confirm exit 0. → exit 0.
- [x] 4.6 Run `openspec validate correct-presentation-alias-misclassification-4-11-2 --strict` and confirm the active change remains valid, unsynchronized, and unarchived. → `Change 'correct-presentation-alias-misclassification-4-11-2' is valid`. Active change remains under `openspec/changes/correct-presentation-alias-misclassification-4-11-2/`.

## 5. Completion Report

- [x] 5.1 Report the exact root cause, files changed, presentation aliases changed, tests added, all command results, and confirmation that no embedding model, Ollama configuration, vector data, calibration dataset, recognizer mode, HTTP contract, handler behavior, or order transaction semantics changed.

  **Root cause:** `backend/recognizers/product_recognizer.py` had `PRESENTACION_ALIASES["picante"] = "picante"`. The `_extraer_presentacion` helper returned `"picante"` for any user input containing the token, and the post-filter in `detectar_productos` then discarded every candidate whose `presentacion_codigo` did not match. The catalog only models `picante` as a flavor inside `producto_nombre` (e.g., `Empanada de Carne Picante` with `presentacion_codigo = "unidad"`), so the valid destination was repeatedly thrown away and the real `modificar_producto` flow treated the destination as unknown.

  **Files changed:**
  - `backend/recognizers/product_recognizer.py` — removed the single `picante → picante` line from `PRESENTACION_ALIASES`. All other aliases (`chica`, `chico`, `chiqui`, `pequena`, `pequeno`, `familiar`, `fami`, `gran`, `grande`, `grandi`, `individual`, `unidad`, `lata`, `litro`, `litros`, `medio`, `tradicional`) and all other recognizer logic (`_extraer_presentacion`, `_extraer_candidatos`, `_filtrar_por_tokens_clave`, `_calcular_score`, `_segmentar_pedido`, presentation filter, output shape) are unchanged.
  - `backend/tests/test_product_recognizer.py` — added new `DetectarProductosPresentacionTest` class with 7 tests:
    - `test_picante_no_esta_en_presentacion_aliases`
    - `test_descriptor_picante_no_filtra_candidato_unidad` (the direct defect)
    - `test_termino_legitimo_grande_filtra_candidato_correcto`
    - `test_termino_legitimo_chica_filtra_candidato_correcto`
    - `test_termino_legitimo_lata_filtra_candidato_correcto`
    - `test_termino_presentacion_desconocido_no_filtra_unidad`
    - `test_presentacion_aliases_incluye_terminos_legitimos`
  - `backend/tests/test_llm_settings.py` — `test_embedding_overrides_apply` now uses `test-embedding-model` as the override and assertion value (was `nomic-embed-text`). Production defaults and the environment-override test purpose are preserved.
  - `openspec/specs/project.md` — replaced the pending implementation prompt with the proper `### Subphase 4.11.2 — Correct Presentation Alias Misclassification in Product Recognition [ ] — pending` entry (objective, context, scope, out-of-scope, files affected).
  - `openspec/changes/correct-presentation-alias-misclassification-4-11-2/tasks.md` — this artifact; checkboxes updated with execution notes.

  **Presentation aliases changed:** only `picante → picante` removed; `tradicional` preserved (no catalog evidence of the same misclassification).

  **Confirmation of invariants (no changes to):**
  - Embedding model: production defaults unchanged (`all-minilm:latest`); only the test override fixture became `test-embedding-model`.
  - Ollama configuration: untouched.
  - Vector data: untouched.
  - Calibration dataset: untouched. `openspec/specs/calibrate-hybrid-product-recognition-4-11/`, `openspec/specs/expand-product-recognition-calibration-dataset-4-11-1/`, and related modules are not modified.
  - Recognizer mode selection: `product_recognizer_mode` setting, factory, and shadow/hybrid services are untouched.
  - HTTP contract: all routers, handlers, request/response schemas, and the real `modificar_producto` HTTP flow are untouched.
  - Handler behavior: untouched.
  - Order transaction semantics: untouched. The defect fix is isolated to the recognizer's static alias map.

  **Test results:**
  - `pytest` for the two real-flow defects + `test_llm_settings.py` → **14/14 passed**.
  - Focused product recognizer tests → **12/12 passed**.
  - `ruff check` on touched files → clean for the files I touched; 3 pre-existing B017 errors in `test_llm_settings.py` are reported separately and were not introduced by this change.
  - `mypy --strict` on `product_recognizer.py` → 16 pre-existing `Missing type arguments for generic type "dict"` / `"tuple"` errors, none on the line I touched; confirmed identical before/after by `git stash`.
  - `compileall` on touched files → exit 0.
  - `openspec validate … --strict` → `Change 'correct-presentation-alias-misclassification-4-11-2' is valid`.

- [x] 5.2 Leave the change under `openspec/changes/correct-presentation-alias-misclassification-4-11-2/`; do not run specification sync or archive.
