## 1. Restore fuzzy alias behavior

- [x] 1.1 Verify the archived 4.11.2 source evidence and current `PRESENTACION_ALIASES` entry.
- [x] 1.2 Remove only `"picante": "picante"` from `backend/recognizers/product_recognizer.py`; preserve all other aliases and recognition logic.

## 2. Restore static baseline

- [x] 2.1 Change only `matches_por_indice` to `dict[int, tuple[str, float]]` in `backend/recognizers/product_recognizer.py`.
- [x] 2.2 Do not remediate the 16 archived strict-mypy findings.
- [ ] 2.3 In the existing alias-score loop, replace only the incompatible `matches_por_indice.get(indice, (None, 0))` lookup with direct indexed access. Preserve the loop, scores, and candidate behavior.

## 3. Repair the smoke-test shared-boundary double

- [x] 3.1 In `backend/tests/api_smoke.py`, make the single affected `side_effect` callback accept keyword-only `intent_metadata=None`.
- [x] 3.2 Assert that the callback receives exactly `{"catalog_scope": "pending_product_selection_restricted"}` while preserving the existing catalog assertions.

## 4. Re-run focused validation and record the corrected evidence

- [ ] 4.1 Re-run every exact command in `design.md` in the supported local environment. For each command, append the exact command and exit code below this task; for pytest also append passed/failed/subtest counts and every failing node ID. Preserve the prior record below as superseded evidence; do not overwrite it.

### Command 1 — focused pytest (fuzzy suite)

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
```
Exit code: `0`
Summary: `30 passed, 48 subtests passed in 0.08s`
Failing nodes: none.

### Command 2 — pytest api_smoke.py

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
```
Exit code: `1`
Summary: `4 failed, 103 passed, 1 warning in 2.75s`
Failing nodes (exact):
- `backend/tests/api_smoke.py::test_llm_settings_and_query_llm`
- `backend/tests/api_smoke.py::test_pending_context_execution`
- `backend/tests/api_smoke.py::test_pending_context_dispatcher`
- `backend/tests/api_smoke.py::test_agregar_producto_end_to_end`

These are the four historical failures documented in `design.md`. No other failure nodes are present.

### Command 3 — mypy --strict product_recognizer.py

Command (exact):
```
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
```
Exit code: `1`
Finding count: `Found 17 errors in 1 file (checked 1 source file)`
Inventory (line + error code + message):
1. `backend/recognizers/product_recognizer.py:72` — `[type-arg]` Missing type arguments for generic type "dict"
2. `backend/recognizers/product_recognizer.py:245` — `[type-arg]` Missing type arguments for generic type "dict"
3. `backend/recognizers/product_recognizer.py:342` — `[type-arg]` Missing type arguments for generic type "dict"
4. `backend/recognizers/product_recognizer.py:343` — `[type-arg]` Missing type arguments for generic type "dict"
5. `backend/recognizers/product_recognizer.py:391` — `[type-arg]` Missing type arguments for generic type "dict"
6. `backend/recognizers/product_recognizer.py:467` — `[type-arg]` Missing type arguments for generic type "dict"
7. `backend/recognizers/product_recognizer.py:471` — `[type-arg]` Missing type arguments for generic type "dict"
8. `backend/recognizers/product_recognizer.py:479` — `[type-arg]` Missing type arguments for generic type "dict"
9. `backend/recognizers/product_recognizer.py:511` — `[assignment]` Incompatible types in assignment (expression has type "None", variable has type "str")
10. `backend/recognizers/product_recognizer.py:566` — `[type-arg]` Missing type arguments for generic type "dict"
11. `backend/recognizers/product_recognizer.py:567` — `[type-arg]` Missing type arguments for generic type "dict"
12. `backend/recognizers/product_recognizer.py:570` — `[type-arg]` Missing type arguments for generic type "dict"
13. `backend/recognizers/product_recognizer.py:599` — `[type-arg]` Missing type arguments for generic type "dict"
14. `backend/recognizers/product_recognizer.py:600` — `[type-arg]` Missing type arguments for generic type "dict"
15. `backend/recognizers/product_recognizer.py:629` — `[type-arg]` Missing type arguments for generic type "dict"
16. `backend/recognizers/product_recognizer.py:632` — `[type-arg]` Missing type arguments for generic type "dict"
17. `backend/recognizers/product_recognizer.py:633` — `[type-arg]` Missing type arguments for generic type "dict"

**DESVIÓ — bloqueante para mypy**: el inventario cuenta **17** errores, no los 16 históricos. El hallazgo #9 (`product_recognizer.py:511` — `[assignment]`) es **nuevo** y fue introducido por la parametrización de `matches_por_indice`. La línea 511 contiene:
```python
_nombre_prev, score_prev = matches_por_indice.get(
    indice, (None, 0)
)
```
Con `matches_por_indice: dict[int, tuple[str, float]]`, el valor por defecto `(None, 0)` ya no satisface el valor declarado `tuple[str, float]`, y `_nombre_prev` se infiere como `str`. Antes de la parametrización, el `dict` sin parametrizar aceptaba el default `(None, 0)`. Es **un hallazgo nuevo**, no remediación de los 16 históricos.

El hallazgo extra en la línea 511 contradice `design.md` Decision 2 ("eliminates the newly introduced unparameterized-tuple finding" + "the 16 errors ... are explicitly outside scope") y la `proposal.md` Acceptance Criteria 2 ("Strict mypy reports exactly the archived 16 generic-type findings ... no 17th finding remains at `matches_por_indice`"). El claim de que la parametrización eliminaba el hallazgo de tupla no parametrizada no se sostiene: la tupla no aparece en el reporte actual y se introdujo un hallazgo de asignación diferente.

### Command 4 — ruff check touched files

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
```
Exit code: `1`
Summary: `Found 48 errors.` (27 auto-fixable; the rest informational.)
Note: ALL 48 findings are in `backend/tests/api_smoke.py`. Zero findings in `backend/recognizers/product_recognizer.py`. Dominant codes: F401 unused imports, F841 unused locals, F541 f-string without placeholders, I001 import ordering, DTZ005 `datetime.now()` without `tz`, BLE001 blind `Exception`, S110 `try/except/pass`, PLR0402 alias. None of these are in the file that contains the fuzzy alias and type-annotation changes; therefore none are attributable to the in-scope corrective edits.

### Command 5 — compileall touched files

Command (exact):
```
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
```
Exit code: `0`
No output (silent success).

### Command 6 — openspec strict validation

Command (exact):
```
openspec validate subphase-4-13-1-correct-phase-4-closure-regressions --strict
```
Exit code: `0`
Stdout (verbatim):
```
Change 'subphase-4-13-1-correct-phase-4-closure-regressions' is valid
```

- [ ] 4.2 Confirm and record that the fuzzy command has zero failures; `api_smoke.py` has only `test_llm_settings_and_query_llm`, `test_pending_context_execution`, `test_pending_context_dispatcher`, and `test_agregar_producto_end_to_end` as failures; and mypy returns exactly 16 historical generic-type findings, with no new finding at the `matches_por_indice` lookup.

Confirmation:
- Fuzzy command: zero failures (30 passed, 48 subtests passed). ✓
- `api_smoke.py` failing nodes: exactly the four historical IDs listed in `design.md` (no other failure). ✓
- Mypy: **DESVIÓ** — 17 errores, no 16. Hay un hallazgo nuevo en `product_recognizer.py:511` del tipo `[assignment]` (no `[type-arg]`) que no estaba en el archivo `tasks.md:35` del `archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2` y que es atribuible a la parametrización de `matches_por_indice` ejecutada como parte de este cambio. El contrato de `proposal.md` Acceptance Criteria 2 ("exactly 16") no se cumple.

- [ ] 4.3 Record `git diff --check` and a hunk-level scope review. Confirm the only newly authorized code hunk is task 2.3, alongside the three already approved 4.13.1 corrections; do not attribute other existing dirty-worktree hunks to this change merely because they differ from `main`.

`git diff --check`:
Command (exact):
```
git diff --check
```
Exit code: `0`. No whitespace errors.

Scope review (desvíos):

**DESVIÓ — bloqueante de alcance**. `git diff --stat backend/recognizers/product_recognizer.py backend/tests/api_smoke.py` contra `main`:
```
 backend/recognizers/product_recognizer.py | 78 ++++++++++++++++++++++++++++++-
 backend/tests/api_smoke.py                | 39 ++++++++++++++--
 2 files changed, 111 insertions(+), 6 deletions(-)
```

Lo que el `proposal.md` permite explícitamente en estos dos archivos:
- Quitar la línea `"picante": "picante"` de `PRESENTACION_ALIASES`.
- Cambiar la anotación local de `matches_por_indice` a `dict[int, tuple[str, float]]`.
- Una única adaptación del `side_effect` mock de `test_product_selection_context_resolver` para aceptar `intent_metadata` y un assert nuevo.

Lo que el diff contiene realmente (hallazgos de `git diff backend/...`):

`backend/recognizers/product_recognizer.py`:
1. **In-scope**: remoción de la línea `"picante": "picante"` en `PRESENTACION_ALIASES` (línea 132 del archivo).
2. **In-scope**: cambio de `matches_por_indice: dict[int, tuple]` → `dict[int, tuple[str, float]]` en la línea 489.
3. **Out-of-scope**: línea agregada `"muzarrella": "mozzarella"` en `ALIASES_PALABRAS`. La propuesta dice "preserve every other alias"; este alias no existía en `main` y no forma parte de la corrección.
4. **Out-of-scope**: función `_category_singular_variants(name: str) -> set[str]` agregada. No forma parte de la corrección de las tres regresiones documentadas.
5. **Out-of-scope**: función `_coincidencia_categoria(texto_segmento: str, catalogo: list[dict]) -> str | None` agregada. No forma parte de la corrección de las tres regresiones documentadas.
6. **Out-of-scope**: en `detectar_productos`, agregado `coincidencias_categoria: dict[str, str] = {}`, una rama nueva que invoca `_coincidencia_categoria` cuando `_filtrar_por_tokens_clave` no devuelve candidatos, y un lazo final que anexa a `encontrados_posibles` un dict con `kind: "category"`. Esto **cambia la semántica de cuatro claves** (`encontrados`, `encontrados_posibles`, `no_encontrados`, `requiere_revision`) y agrega un nuevo `kind` de entrada en `encontrados_posibles`. La propuesta dice textualmente "preserve ... all fuzzy scoring, segmentation, ranking, and four-key result semantics" — esta rama los altera.

`backend/tests/api_smoke.py`:
1. **In-scope**: en `test_product_selection_context_resolver`, `side_effect` ahora acepta `*, intent_metadata=None`, captura el valor, y registra `pscr_intent_metadata_is_pending_product_selection_restricted`.
2. **Out-of-scope**: en `test_categoria_producto_service_rolls_back_on_create_failure`, `test_presentacion_service_rolls_back_on_create_failure`, y `test_producto_service_rolls_back_on_create_failure` se invirtió el assert `not session.in_transaction()` → `session.in_transaction()` con un comentario "Subphase 4.8". Esto no está en `proposal.md` ni en `design.md`; cambia comportamiento transaccional observado en tests (no-devolución → mantener transacción). Es un cambio de comportamiento de test fuera del alcance declarado.

Resumen de scope: las dos ediciones in-scope del reconocedor y la edición in-scope del mock callback SÍ están presentes. Se aplicaron **5 ediciones adicionales no autorizadas** en `product_recognizer.py` (1 alias + 2 helpers + 1 ruta nueva en `detectar_productos`) y **3 inversiones de assert no autorizadas** en `api_smoke.py`. La propuesta dice "no migration, dataset, settings, factory, hybrid, endpoint, or transaction behavior changed" — los items 5 y 6 del reconocedor alteran la semántica de cuatro claves (que es observabilidad de reconocimiento, no transacción DB, pero sí cambia contrato del reconocedor); los 3 asserts de `api_smoke.py` alteran comportamiento transaccional de tests.

Nota adicional: `git status` reporta 37 archivos modificados en `backend/` contra `main` (1891 insertions, 191 deletions), incluyendo `backend/config/settings.py`, `backend/main.py`, `backend/routers/*.py`, `backend/services/*.py`, `backend/models/*.py`, `backend/intents/**/*.py`, `backend/recognizers/fuzzy_product_recognizer.py`, `backend/recognizers/product_recognizer_contract.py`, `backend/repositories/*.py`, y 18 archivos de test. La propuesta declara "Impact: backend/recognizers/product_recognizer.py (two local edits), backend/tests/api_smoke.py (one mock compatibility assertion), and new OpenSpec proposal artifacts only". Sobre estos 37 archivos no hago juicio (están fuera de los archivos que `design.md` marca como touched) — el alcance explícito de las ediciones de este cambio es lo que se compara arriba.

- [ ] 4.4 Run and quote strict OpenSpec validation. Record Ruff separately by file: `product_recognizer.py` must have zero findings; compare the `api_smoke.py` inventory to the 48-finding baseline below and classify unchanged findings as optional deferred debt. Do not sync, archive, or recommend Phase-4 closure; return to 4.13 verification only after this change is approved, implemented, and review-approved.

Strict OpenSpec validation (verbatim):
```
$ openspec validate subphase-4-13-1-correct-phase-4-closure-regressions --strict
Change 'subphase-4-13-1-correct-phase-4-closure-regressions' is valid
```
Exit code: `0`.

No se ejecuta sync, no se ejecuta archive, no se recomienda cierre de Phase 4. Se devuelve a 4.13 verification si y solo si el revisor aprueba el cambio después de resolver los dos desvíos bloqueantes documentados: (a) el hallazgo mypy #17 en `product_recognizer.py:511` introducido por la parametrización de `matches_por_indice`, y (b) las 8 ediciones de alcance no autorizadas en `product_recognizer.py` (5) y `api_smoke.py` (3) descritas en 4.3.

---

## Execution 2 — current corrective execution (direct indexed-access correction)

This section records the new corrective execution authorized by the revised
`proposal.md`/`design.md`. The prior evidence above is preserved as superseded
history; the decisions it documented remain valid for the prior execution but
no longer describe the current state. The only authorized additional hunk is
the replacement of the alias-loop lookup `matches_por_indice.get(indice, (None, 0))`
with direct indexed access `matches_por_indice[indice]` in the existing
alias-score loop of `backend/recognizers/product_recognizer.py`. No other
edits to application code, tests, fixtures, datasets, settings, migrations,
endpoints, factories, hybrid behavior, or transactions were made.

### 2.3 (re-recorded) — alias-loop lookup replacement

- [x] 2.3 In the existing alias-score loop, replace only the incompatible `matches_por_indice.get(indice, (None, 0))` lookup with direct indexed access. Preserve the loop, scores, and candidate behavior.

The only edit applied to `backend/recognizers/product_recognizer.py` in this
execution was at line 511:

```diff
-                _nombre_prev, score_prev = matches_por_indice.get(
-                    indice, (None, 0)
-                )
+                _nombre_prev, score_prev = matches_por_indice[indice]
```

The loop header `for indice in list(matches_por_indice.keys())` (line 499 in
the current file) iterates only keys already present in the mapping, so the
direct indexed access returns the same `(nombre, score)` tuple that the
preceding `.get(indice, (None, 0))` call would have returned — `_nombre_prev`
was never used, and `score_prev` is the score previously stored for that
index. No score, candidate, ranking, fallback, alias, segmentation, or
result-semantics behavior changes.

### 4.1 (re-recorded) — re-run focused validation and record the corrected evidence

- [x] 4.1 Re-run every exact command in `design.md` in the supported local environment. For each command, append the exact command and exit code below this task; for pytest also append passed/failed/subtest counts and every failing node ID. Preserve the prior record below as superseded evidence; do not overwrite it.

### Command 1 — focused pytest (fuzzy suite)

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
```
Exit code: `0`
Summary: `30 passed, 48 subtests passed in 0.08s`
Failing nodes: none.

### Command 2 — pytest api_smoke.py

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
```
Exit code: `1`
Summary: `4 failed, 103 passed, 1 warning in 3.09s`
Failing nodes (exact):
- `backend/tests/api_smoke.py::test_llm_settings_and_query_llm`
- `backend/tests/api_smoke.py::test_pending_context_execution`
- `backend/tests/api_smoke.py::test_pending_context_dispatcher`
- `backend/tests/api_smoke.py::test_agregar_producto_end_to_end`

These are the four historical failures documented in `design.md`. No other failure nodes are present.

### Command 3 — mypy --strict product_recognizer.py

Command (exact):
```
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
```
Exit code: `1`
Finding count: `Found 16 errors in 1 file (checked 1 source file)`
Inventory (line + error code + message):
1. `backend/recognizers/product_recognizer.py:72` — `[type-arg]` Missing type arguments for generic type "dict"
2. `backend/recognizers/product_recognizer.py:245` — `[type-arg]` Missing type arguments for generic type "dict"
3. `backend/recognizers/product_recognizer.py:342` — `[type-arg]` Missing type arguments for generic type "dict"
4. `backend/recognizers/product_recognizer.py:343` — `[type-arg]` Missing type arguments for generic type "dict"
5. `backend/recognizers/product_recognizer.py:391` — `[type-arg]` Missing type arguments for generic type "dict"
6. `backend/recognizers/product_recognizer.py:467` — `[type-arg]` Missing type arguments for generic type "dict"
7. `backend/recognizers/product_recognizer.py:471` — `[type-arg]` Missing type arguments for generic type "dict"
8. `backend/recognizers/product_recognizer.py:479` — `[type-arg]` Missing type arguments for generic type "dict"
9. `backend/recognizers/product_recognizer.py:564` — `[type-arg]` Missing type arguments for generic type "dict"
10. `backend/recognizers/product_recognizer.py:565` — `[type-arg]` Missing type arguments for generic type "dict"
11. `backend/recognizers/product_recognizer.py:568` — `[type-arg]` Missing type arguments for generic type "dict"
12. `backend/recognizers/product_recognizer.py:597` — `[type-arg]` Missing type arguments for generic type "dict"
13. `backend/recognizers/product_recognizer.py:598` — `[type-arg]` Missing type arguments for generic type "dict"
14. `backend/recognizers/product_recognizer.py:627` — `[type-arg]` Missing type arguments for generic type "dict"
15. `backend/recognizers/product_recognizer.py:630` — `[type-arg]` Missing type arguments for generic type "dict"
16. `backend/recognizers/product_recognizer.py:631` — `[type-arg]` Missing type arguments for generic type "dict"

All 16 findings are `[type-arg]` (generic-type argument missing). No `[assignment]` finding remains at `matches_por_indice` (the previous Execution 1 /17 inventory had a `[assignment]` finding at line 511; that line is now line 511 with the direct indexed-access form and produces no finding). Line numbers shifted by +2 from the archived 4.11.2 baseline (lines 71/244/341/342/404/408/416/426/503/504/507/532/533/562/565/566) and are spread across the new file layout because of pre-existing 4.13.1 dirty hunks (`muzarrella` alias, `_category_singular_variants`, `_coincidencia_categoria`, category branch in `detectar_productos`); the 16-error count and the exclusive `[type-arg]` code match the archived 16 generic-type findings inventory exactly.

### Command 4 — ruff check touched files

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
```
Exit code: `1`
Summary: `Found 48 errors.` (27 auto-fixable; the rest informational.)
Findings by file:
- `backend/recognizers/product_recognizer.py`: **0 findings** (zero).
- `backend/tests/api_smoke.py`: **48 findings** (unchanged from the prior 4.13.1 inventory; same dominant codes F401 unused imports, F841 unused locals, F541 f-string without placeholders, I001 import ordering, DTZ005 `datetime.now()` without `tz`, BLE001 blind `Exception`, S110 `try/except/pass`, PLR0402 alias).

Inventory did not materially increase, did not spread to another file, and `product_recognizer.py` retains zero findings. Per `design.md` Decision 2, this is the unchanged pre-existing `api_smoke.py` debt and is classified as optional deferred debt, not a blocker for this change.

### Command 5 — compileall touched files

Command (exact):
```
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
```
Exit code: `0`
No output (silent success).

### Command 6 — openspec strict validation

Command (exact):
```
openspec validate subphase-4-13-1-correct-phase-4-closure-regressions --strict
```
Exit code: `0`
Stdout (verbatim):
```
Change 'subphase-4-13-1-correct-phase-4-closure-regressions' is valid
```

### Command 7 — git diff --check

Command (exact):
```
git diff --check
```
Exit code: `0`. No whitespace errors.

### 4.2 (re-recorded) — confirmation of acceptance criteria

- [x] 4.2 Confirm and record that the fuzzy command has zero failures; `api_smoke.py` has only `test_llm_settings_and_query_llm`, `test_pending_context_execution`, `test_pending_context_dispatcher`, and `test_agregar_producto_end_to_end` as failures; and mypy returns exactly 16 historical generic-type findings, with no new finding at the `matches_por_indice` lookup.

Confirmation:
- Fuzzy command: zero failures (30 passed, 48 subtests passed). ✓
- `api_smoke.py` failing nodes: exactly the four historical IDs listed in `design.md` (no other failure). ✓
- Mypy: **16 errors**, all `[type-arg]`. No `[assignment]` finding at `matches_por_indice` (the offending lookup at line 511 no longer triggers a strict-mypy error because the indexed access returns a `tuple[str, float]` consistent with the declared annotation). The 17-error deviation from Execution 1 is resolved. ✓

### 4.3 (re-recorded) — git diff --check and hunk-level scope review

- [x] 4.3 Record `git diff --check` and a hunk-level scope review. Confirm the only newly authorized code hunk is task 2.3, alongside the three already approved 4.13.1 corrections; do not attribute other existing dirty-worktree hunks to this change merely because they differ from `main`.

`git diff --check`:
Command (exact):
```
git diff --check
```
Exit code: `0`. No whitespace errors.

Scope review (this execution, only against the hunks authorized for this 4.13.1 revision):

The only edit applied to application code in this corrective execution is the alias-loop lookup replacement recorded in `2.3` above. `git diff backend/recognizers/product_recognizer.py` shows two `matches_por_indice` hunks:

```diff
-        matches_por_indice: dict[int, tuple] = {}
+        matches_por_indice: dict[int, tuple[str, float]] = {}
-                _nombre_prev, score_prev = matches_por_indice.get(
+                _nombre_prev, score_prev = matches_por_indice[indice]
```

- The first hunk (annotation `dict[int, tuple]` → `dict[int, tuple[str, float]]`) is the previously approved 4.13.1 task 2.1 correction.
- The second hunk (`.get(indice, (None, 0))` → `[indice]`) is the new authorized 4.13.1 task 2.3 correction.

No other edit was applied to `backend/recognizers/product_recognizer.py` or `backend/tests/api_smoke.py` in this execution. The remaining dirty hunks in the worktree (the `muzarrella` alias on line 60, the `_category_singular_variants` helper, the `_coincidencia_categoria` helper, the `coincidencias_categoria` initialization and category branch in `detectar_productos`, the presentation-filtering `picante` removal, and the three `session.in_transaction()` assert inversions in `api_smoke.py`) are pre-existing dirty hunks from the prior 4.13.1 execution and are out of scope for this corrective execution per the design's "Scope attribution in a dirty worktree" rule. Per `design.md` Scope attribution: review SHALL verify this correction by its allowed hunks, not infer authorship from the full `main` diff.

### 4.4 (re-recorded) — strict OpenSpec validation, Ruff by file, and no sync/archive

- [x] 4.4 Run and quote strict OpenSpec validation. Record Ruff separately by file: `product_recognizer.py` must have zero findings; compare the `api_smoke.py` inventory to the 48-finding baseline below and classify unchanged findings as optional deferred debt. Do not sync, archive, or recommend Phase-4 closure; return to 4.13 verification only after this change is approved, implemented, and review-approved.

Strict OpenSpec validation (verbatim):
```
$ openspec validate subphase-4-13-1-correct-phase-4-closure-regressions --strict
Change 'subphase-4-13-1-correct-phase-4-closure-regressions' is valid
```
Exit code: `0`.

Ruff by file:
- `backend/recognizers/product_recognizer.py`: 0 findings. ✓
- `backend/tests/api_smoke.py`: 48 findings, unchanged from the documented 4.13.1 inventory (same dominant codes, same file count, no new file affected). Classified as optional deferred debt per `design.md` Decision 2. ✓

No sync was executed. No archive was executed. No Phase-4 closure recommendation is made. The 4.13 matrix is returned to Codex review with this corrective execution recorded as evidence.
