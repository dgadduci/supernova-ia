## 1. Pre-flight and evidence

- [x] 1.1 Confirm no active OpenSpec change duplicates this closure change and preserve all pre-existing worktree changes.
- [x] 1.2 Record the current commit, worktree status, Python/venv execution status, and the exact archived-debt baselines cited in `proposal.md`.
- [x] 1.3 Do not edit application code, tests, fixtures, data, settings, migrations, project roadmap, or archived changes.

## 2. Required Phase-4 regression surface

- [x] 2.1 Run the fuzzy command in `design.md` and record the node-level result. → 28/30 passed; **2 failed** in required fuzzy matrix:
  - `backend/tests/test_product_recognizer.py::DetectarProductosPresentacionTest::test_picante_no_esta_en_presentacion_aliases`
  - `backend/tests/test_product_recognizer.py::DetectarProductosPresentacionTest::test_descriptor_picante_no_filtra_candidato_unidad`
  Both fail because `'picante': 'picante'` is still present in `PRESENTACION_ALIASES` (line 136 of `backend/recognizers/product_recognizer.py`). The 4.11.2 archive documented the deletion of that line as the fix; the committed HEAD has not landed that deletion. These are required-matrix failures (not optional debt).
- [x] 2.2 Run the vector/embedding command in `design.md` and record the node-level result. → 92 passed, 58 subtests passed (exit 0).
- [x] 2.3 Run the shadow command in `design.md` and record the node-level result. → 55 passed, 54 subtests passed (exit 0).
- [x] 2.4 Run the calibration command group in `design.md`; record the node-level result and the calibration report eligibility. → 207 passed, 15 subtests passed (exit 0).
- [x] 2.5 Run the pending selection/ambiguity command in `design.md` and record the node-level result. → 105 passed, 29 subtests passed (exit 0).
- [x] 2.6 Run the settings/factory/controlled-hybrid command in `design.md` and record the node-level result. → 76 passed (exit 0).
- [x] 2.7 Run the calibration CLI command in `design.md`; inspect `/private/tmp/phase-4-13-calibration.json` and verify `eligibility.status == "eligible"`. → CLI exit 0; `cases=47 policies=243 eligibility=eligible`; `eligibility.status == "eligible"`.

## 3. Static validation

- [x] 3.1 Run the focused Ruff command in `design.md`; zero findings are required in all listed Phase-4 files. → `All checks passed!` (exit 0).
- [x] 3.2 Run the focused `compileall` command in `design.md`; exit code zero is required. → exit 0.
- [x] 3.3 Run `openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict`; it must report valid. → `Change 'subphase-4-13-global-regression-debt-verification-phase-4-closure' is valid`.

## 4. Debt verification and closure decision

- [x] 4.1 Run each separate optional-debt command in `design.md` without altering the result.
  - `PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py` → **5 failed**, 102 passed (4 archived + 1 new).
  - `PYTHONPATH=. venv/bin/python -m ruff check backend/tests/test_llm_settings.py` → 3 B017 at lines 28, 120, 122.
  - `PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py` → 17 errors (vs archived baseline of 16).
- [x] 4.2 Classify each observed issue:
  - `test_picante_no_esta_en_presentacion_aliases` + `test_descriptor_picante_no_filtra_candidato_unidad` → **`new_regression`** in the **required fuzzy matrix** (not optional debt). The committed HEAD does not reflect the 4.11.2 fix; `PRESENTACION_ALIASES` still maps `"picante" → "picante"`, which causes the fuzzy recognizer to filter out valid candidates like `Empanada de Carne Picante`. The 4.11.2 archive documents the line deletion as already applied, so this is not an unchanged excluded baseline.
  - `api_smoke.py::test_product_selection_context_resolver` → **`new_regression`** (optional debt materially increased). The archived baseline (4.8/4.12A) listed four pre-existing smoke failures; this is a fifth failure not in that documented set. Increase in documented debt blocks per proposal.
  - `api_smoke.py::test_llm_settings_and_query_llm`, `test_pending_context_execution`, `test_pending_context_dispatcher`, `test_agregar_producto_end_to_end` → **`verified_pre_existing`** (matches the four archived baseline cases by name).
  - `backend/tests/test_llm_settings.py` B017 at lines 28/120/122 → **`verified_pre_existing`** (matches the 4.11.2 archived baseline exactly; no drift).
  - `backend/recognizers/product_recognizer.py` mypy → **`new_regression`** (optional debt materially increased). Baseline had 16 generic-type errors at lines 71/244/341/342/404/408/416/426/503/504/507/532/533/562/565/566; current has 17 errors (the 16 baseline errors shifted +1 line due to added imports, plus one new `Missing type arguments for generic type "tuple"` at line 490 `matches_por_indice: dict[int, tuple] = {}`). An increased inventory blocks closure per the proposal's mypy-specific rule.
- [x] 4.3 Block closure only for a required-command failure, non-eligible calibration result, a `new_regression` that is materially new/increases documented debt/changes runtime-business behavior/overlaps the required matrix, or an environment blocker that has not subsequently been cleared by successful execution in the supported local environment.
  - Required matrix: fuzzy suite has 2 failures (blocks).
  - Optional debt materially increased: `test_product_selection_context_resolver` (blocks).
  - Optional debt materially increased: mypy 16→17 (blocks).
  - Calibration CLI eligible (does not block).
  - No environment blockers observed; all commands executed successfully in the supported local environment (Python 3.14.6, venv).
- [x] 4.4 Recommend Phase-4 closure only when all acceptance criteria in `design.md` hold; otherwise propose a narrowly-scoped corrective change. Do not implement it.
  - **Closure recommendation: DO NOT close Phase 4.** Three independent blocking conditions are present:
    1. Required fuzzy matrix has 2 failures (`test_picante_no_esta_en_presentacion_aliases`, `test_descriptor_picante_no_filtra_candidato_unidad`).
    2. Optional debt increased: `api_smoke.py::test_product_selection_context_resolver` is a fifth failure beyond the archived 4-case baseline.
    3. Optional debt increased: mypy generic-type inventory grew from 16 to 17 errors.
  - Suggested narrowly-scoped corrective change (separate OpenSpec change, not implemented here): remove `"picante": "picante"` from `PRESENTACION_ALIASES` in `backend/recognizers/product_recognizer.py` (the documented 4.11.2 fix), re-run the fuzzy suite to confirm it goes green, then re-investigate the new smoke and mypy findings in the context of the post-fix state.
- [x] 4.5 Do not sync or archive this change or Phase 4; wait for explicit user approval.

## 5. Re-verification evidence (post 4.13.1 corrective change approval)

This section records the re-verification of the Phase-4 closure matrix after the
approval of `subphase-4-13-1-correct-phase-4-closure-regressions`. The prior
evidence above (sections 1–4) is preserved as supersedeable history; the
decisions recorded there describe the pre-4.13.1 state. The only files
permitted to be modified for this re-verification are this `tasks.md` and the
read-only `design.md`/`proposal.md` artifacts; no application code, test,
fixture, dataset, settings, migration, archived change, or roadmap was
modified. Python 3.14.6 in `venv/bin/` was the executable for every command.
HEAD at the start of this re-verification was `628e65bcd532159384681c0a4f356013a7ba972b`
on branch `main`, and the pre-existing dirty worktree was preserved intact.

### 5.1 Calibration report eligibility

- File: `/private/tmp/phase-4-13-calibration.json`.
- Mtime: `Aug 6 02:07:23 2026` (the file was rewritten by the calibrated CLI
  run executed in §5.2 below).
- `eligibility.status`: **`"eligible"`** (confirmed by
  `python3 -c "import json; d=json.load(open('/private/tmp/phase-4-13-calibration.json')); print(d['eligibility']['status'])"`).
- `case_count`: `47`. `policy_count`: `243`. Other top-level keys:
  `case_results`, `commerce_catalog_cache_size`, `comparison`,
  `dataset_fingerprint`, `dataset_version`, `eligibility`, `failed_case_ids`,
  `fuzzy_metrics`, `hybrid_metrics`, `infrastructure_failures`, `latency_p50`,
  `latency_p95`, `mismatch_category_counts`, `policies`, `policy_count`,
  `selected_policy`, `vector_metrics`.

### 5.2 Required Validation commands from `design.md`

Each command is reproduced verbatim, with its exit code, pytest summary
(where applicable), and every failing node ID.

#### Command 5.2.1 — Fuzzy required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
```
Exit code: `0`.
Summary: `30 passed, 48 subtests passed in 0.08s`.
Failing nodes: none.
Comparison with baseline: matches the post-4.13.1 expected state (the
two `picante` regression tests now pass after the alias removal).

#### Command 5.2.2 — Vector/embedding required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_producto_presentacion_embedding_model.py backend/tests/test_producto_presentacion_embedding_integration.py backend/tests/test_producto_presentacion_embedding_indexer.py backend/tests/test_product_presentation_vector_search_service.py backend/tests/test_product_presentation_vector_search_module_boundaries.py backend/tests/test_catalog_embedding_synchronization_service.py
```
Exit code: `0`.
Summary: `92 passed, 58 subtests passed in 2.26s`.
Failing nodes: none.

#### Command 5.2.3 — Shadow required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_shadow_service.py backend/tests/test_product_recognition_shadow_module_boundaries.py backend/tests/test_shadow_metrics_recorder.py
```
Exit code: `0`.
Summary: `55 passed, 54 subtests passed in 0.27s`.
Failing nodes: none.

#### Command 5.2.4 — Calibration required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py backend/tests/test_product_recognition_calibration_eligibility.py backend/tests/test_product_recognition_calibration_report.py backend/tests/test_product_recognition_calibration_policy.py backend/tests/test_product_recognition_calibration_cli.py backend/tests/test_product_recognition_calibration_commerce_catalog.py backend/tests/test_product_recognition_calibration_inventory_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_5.py backend/tests/test_product_recognition_calibration_4_11_7.py
```
Exit code: `0`.
Summary: `207 passed, 15 subtests passed in 0.73s`.
Failing nodes: none.

#### Command 5.2.5 — Pending selection/ambiguity required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py
```
Exit code: `1`.
Summary: `6 failed, 99 passed, 29 subtests passed in 1.26s`.
Failing node IDs (exact):
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionCarneFragmentTest::test_carne_picante_with_product_noun_uniquely_selects_picante`
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionCarneFragmentTest::test_la_picante_with_article_uniquely_selects_picante`
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionCarneFragmentTest::test_picante_uniquely_selects_picante_candidate`
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionCarneFragmentTest::test_picante_with_quantity_4_preserves_cantidad`
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionCarneFragmentTest::test_raw_recognizer_output_for_picante_catalog`
- `backend/tests/test_product_selection_context_resolver.py::ResolveProductSelectionProductoNombreAliasTest::test_substring_picantes_does_not_match_picante_alias`

Classification: **`new_regression` in the required pending matrix**. The
previous 4.13 evidence (§2.5) recorded `105 passed, 29 subtests passed` for
this exact command. The current run reports `99 passed + 6 failed = 105` total
nodes — the same test count, but six previously-green nodes have turned red.
All six failures assert the `presentacion_codigo` alias-narrowing path on
`picante` content (e.g. `result.status == "ready"` for `carne` / `la picante`
/ `picante` / `picante` with quantity, an exact-candidate-index pin for
`test_raw_recognizer_output_for_picante_catalog`, and the
`test_substring_picantes_does_not_match_picante_alias` substring guard). The
4.13.1 corrective change removed the `"picante": "picante"` entry from
`PRESENTACION_ALIASES` in `backend/recognizers/product_recognizer.py` (line
136 → absent; the current mapping at lines 119–137 has no `picante` entry),
so the resolver no longer narrows `picante` via the presentacion-codigo path
and returns `pending_resolution` instead of `ready`. The 4.13.1 task
description did not exercise `test_product_selection_context_resolver.py`,
which is why the corrective change passed its own focused validation while
breaking this required Phase-4 surface. Per `design.md` Decision table,
required-matrix failure blocks closure.

#### Command 5.2.6 — Settings/factory/controlled-hybrid required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_settings_product_recognizer_mode.py backend/tests/test_product_recognition_factory.py backend/tests/test_controlled_hybrid_product_recognition.py
```
Exit code: `0`.
Summary: `76 passed in 0.32s`.
Failing nodes: none.

#### Command 5.2.7 — Calibration CLI

Command (exact):
```
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output /private/tmp/phase-4-13-calibration.json --diagnose --diagnose-output /private/tmp/phase-4-13-calibration.diagnose.json --limit 47
```
Exit code: `0`.
Stdout (verbatim): `cases=47 policies=243 eligibility=eligible`.
Calibration JSON rewritten; `eligibility.status == "eligible"` (see §5.1).

#### Command 5.2.8 — Focused Phase-4 Ruff

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
```
Exit code: `0`.
Stdout: `All checks passed!`.
Findings: **0** (zero). Matches the `design.md` requirement.

#### Command 5.2.9 — Focused compileall

Command (exact):
```
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
```
Exit code: `0`. No output (silent success).

#### Command 5.2.10 — Strict OpenSpec validation

Command (exact):
```
openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict
```
Exit code: `0`.
Stdout (verbatim): `Change 'subphase-4-13-global-regression-debt-verification-phase-4-closure' is valid`.

### 5.3 Optional-debt commands from `design.md`

#### Command 5.3.1 — Smoke (`api_smoke.py`)

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
```
Exit code: `1`.
Summary: `4 failed, 103 passed, 1 warning in 2.63s`.
Failing node IDs (exact):
- `backend/tests/api_smoke.py::test_llm_settings_and_query_llm`
- `backend/tests/api_smoke.py::test_pending_context_execution`
- `backend/tests/api_smoke.py::test_pending_context_dispatcher`
- `backend/tests/api_smoke.py::test_agregar_producto_end_to_end`

Classification: **`verified_pre_existing`**. The four failing node IDs match
the four archived 4.8/4.12A baseline cases listed in `proposal.md` §"Known
debt and closure decision" by exact name. No fifth failure is present
(`test_product_selection_context_resolver`, which was the fifth failure in the
previous 4.13 evidence §4.1, is now green — the 4.13.1 mock-compatibility
fix in `api_smoke.py` is effective). Per `design.md` decision table, exact
documented baseline does not block closure.

#### Command 5.3.2 — Ruff on `test_llm_settings.py`

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/tests/test_llm_settings.py
```
Exit code: `1`.
Findings: **3 B017** at lines **28, 120, 122**, each
`Do not assert blind exception: "Exception"`.
Classification: **`verified_pre_existing`**. Exactly matches the 4.11.2
archived baseline (file `test_llm_settings.py`, 3 B017 at lines 28/120/122)
and `proposal.md` §"Known debt and closure decision". No drift, no spread
to another file, no new code.

#### Command 5.3.3 — mypy strict on `product_recognizer.py`

Command (exact):
```
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
```
Exit code: `1`.
Finding count: `Found 16 errors in 1 file (checked 1 source file)`.
All 16 are `[type-arg]` `Missing type arguments for generic type "dict"`.
Inventory (line + code):
1. `backend/recognizers/product_recognizer.py:72`
2. `backend/recognizers/product_recognizer.py:245`
3. `backend/recognizers/product_recognizer.py:342`
4. `backend/recognizers/product_recognizer.py:343`
5. `backend/recognizers/product_recognizer.py:391`
6. `backend/recognizers/product_recognizer.py:467`
7. `backend/recognizers/product_recognizer.py:471`
8. `backend/recognizers/product_recognizer.py:479`
9. `backend/recognizers/product_recognizer.py:564`
10. `backend/recognizers/product_recognizer.py:565`
11. `backend/recognizers/product_recognizer.py:568`
12. `backend/recognizers/product_recognizer.py:597`
13. `backend/recognizers/product_recognizer.py:598`
14. `backend/recognizers/product_recognizer.py:627`
15. `backend/recognizers/product_recognizer.py:630`
16. `backend/recognizers/product_recognizer.py:631`

Classification: **`verified_pre_existing`**. Exactly 16 historical generic-type
findings, all `[type-arg]`, no `[assignment]` or other new code at
`matches_por_indice` (lines 489 declares `dict[int, tuple[str, float]] = {}`
and line 511 reads `matches_por_indice[indice]` — direct indexed access, no
fallback). Matches the 4.11.2 archived baseline
(`openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/tasks.md:35`)
in count and code; line numbers drift by +2 relative to the archive because
of the pre-existing 4.13.1 dirty hunks that are out of scope per
`design.md` "Scope attribution in a dirty worktree" rule (line-number drift
is permitted per `proposal.md` §"Known debt and closure decision").

### 5.4 `git diff --check`

Command (exact):
```
git diff --check
```
Exit code: `0`. No whitespace errors.

### 5.5 Classification of every observed deviation

| Source | Observation | Class | Blocks? |
| --- | --- | --- | --- |
| Command 5.2.5 (pending, required) | 6 failures in `test_product_selection_context_resolver.py` on `picante` presentacion-codigo narrowing | `new_regression` (required matrix) | **YES** |
| Command 5.3.1 (smoke, optional) | Exactly the 4 named historical failures | `verified_pre_existing` | no |
| Command 5.3.2 (Ruff test_llm_settings) | 3 B017 at 28/120/122 | `verified_pre_existing` | no |
| Command 5.3.3 (mypy) | 16 `[type-arg]` | `verified_pre_existing` (line-number drift only) | no |
| Eligibility | `eligible` | passes | no |
| Ruff Phase 4 | 0 findings | passes | no |
| compileall | exit 0 | passes | no |
| OpenSpec strict | valid | passes | no |
| `git diff --check` | exit 0 | passes | no |
| Environment | Python 3.14.6 / venv, no environment blockers | not a regression | n/a |

### 5.6 Closure recommendation

- **Closure recommendation: DO NOT close Phase 4.**
- One independent blocking condition is present:
  1. **Required pending matrix has 6 failures** in
     `backend/tests/test_product_selection_context_resolver.py`
     (exact 6 node IDs listed in §5.2.5). These tests were green in the
     pre-4.13.1 verification (§2.5 recorded `105 passed`); the 4.13.1
     corrective change removed the `picante → picante` alias entry from
     `PRESENTACION_ALIASES` in `backend/recognizers/product_recognizer.py`,
     which is required by `test_product_recognizer.py::DetectarProductosPresentacionTest`
     but breaks the resolver's `presentacion_codigo` alias-narrowing path
     for `picante` fragments. The 4.13.1 task description did not exercise
     `test_product_selection_context_resolver.py`, so its focused validation
     missed this required-matrix impact. Per `design.md` Decision table,
     required-matrix failure blocks closure.
- Optional debt is fully within allowed boundaries: smoke has exactly the
  4 archived failures, Ruff `test_llm_settings.py` has exactly the 3 archived
  B017 findings, mypy has exactly the 16 archived `[type-arg]` findings with
  no new error at `matches_por_indice`. Recommended closure for the optional
  set is unblocked on those three surfaces.
- Suggested narrowly-scoped corrective change (separate OpenSpec change,
  not implemented here): restore the
  `test_product_selection_context_resolver.py` `picante` narrowing path
  without re-introducing the `"picante": "picante"` alias in
  `PRESENTACION_ALIASES` (e.g. by aligning the resolver's
  presentacion-codigo narrowing with the descriptor-vs-presentation
  distinction that the 4.11.2 archive requires), re-run the pending matrix
  to confirm green, then re-run the fuzzy matrix to confirm the 4.11.2
  invariant is preserved. The 4.13.1 corrective change alone cannot be
  approved while this required-matrix regression persists.
 - No sync, archive, commit, or phase-closure action is performed. The
   final closure decision awaits explicit user approval.

## 6. Re-verification evidence (post 4.13.2 correction approval)

This section is appended after the approved
`subphase-4-13-2-restore-pending-descriptor-narrowing` correction. Sections 1–5
remain historical evidence and are not overwritten. The global matrix was run
from the repository root against the existing dirty worktree. The repository
HEAD was `628e65bcd532159384681c0a4f356013a7ba972b` on `main`; Python 3.14.6
from `venv/bin/` was used. No application code, tests, fixtures, datasets,
settings, migrations, specifications outside this change, archived changes,
or unrelated dirty files were modified.

### 6.1 Calibration CLI report inspection

Command (exact):
```
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output /private/tmp/phase-4-13-calibration.json --diagnose --diagnose-output /private/tmp/phase-4-13-calibration.diagnose.json --limit 47
```

Exit code: `0`.
Stdout (exact): `cases=47 policies=243 eligibility=not_eligible`.

The report `/private/tmp/phase-4-13-calibration.json` was inspected after the
CLI run:

- `eligibility.status`: **`"not_eligible"`**.
- `case_count`: **`47`**.
- `policy_count`: **`243`**.
- `eligibility.reasons`: **`["latency_budget_failed"]`**.
- `hybrid_metrics.latency_p95`: **`748.3454998582602` ms**.
- Dataset `latency_budget_ms_p95`: **`500` ms**.
- `infrastructure_failures`: **`6`**.
- `failed_case_ids`: `c1-colloquial-coca`, `c1-alias-fugazza`,
  `c1-colloquial-coca-cola`, `c1-restricted-cuatro-quesos`,
  `c1-quantity-empanada-carne`, `c1-canonical-fugazzeta`.

The CLI process itself exited zero, but the required eligibility assertion is
not satisfied. This is a required calibration closure blocker, not optional
lint or smoke debt.

### 6.2 Required Phase-4 command matrix

Every command below is reproduced verbatim. Exit codes are from the command
execution; pytest totals and all failing node IDs are recorded.

#### Command 6.2.1 — Fuzzy required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
```

Exit code: `0`.
Summary: `30 passed, 48 subtests passed in 0.14s`.
Failing nodes: none.

#### Command 6.2.2 — Vector/embedding required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_producto_presentacion_embedding_model.py backend/tests/test_producto_presentacion_embedding_integration.py backend/tests/test_producto_presentacion_embedding_indexer.py backend/tests/test_product_presentation_vector_search_service.py backend/tests/test_product_presentation_vector_search_module_boundaries.py backend/tests/test_catalog_embedding_synchronization_service.py
```

Exit code: `0`.
Summary: `92 passed, 58 subtests passed in 4.38s`.
Failing nodes: none.

#### Command 6.2.3 — Shadow required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_shadow_service.py backend/tests/test_product_recognition_shadow_module_boundaries.py backend/tests/test_shadow_metrics_recorder.py
```

Exit code: `0`.
Summary: `55 passed, 54 subtests passed in 0.65s`.
Failing nodes: none.

#### Command 6.2.4 — Calibration required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py backend/tests/test_product_recognition_calibration_eligibility.py backend/tests/test_product_recognition_calibration_report.py backend/tests/test_product_recognition_calibration_policy.py backend/tests/test_product_recognition_calibration_cli.py backend/tests/test_product_recognition_calibration_commerce_catalog.py backend/tests/test_product_recognition_calibration_inventory_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_5.py backend/tests/test_product_recognition_calibration_4_11_7.py
```

Exit code: `0`.
Summary: `207 passed, 15 subtests passed in 2.33s`.
Failing nodes: none.

#### Command 6.2.5 — Pending selection/ambiguity required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py
```

Exit code: `0`.
Summary: `105 passed, 29 subtests passed in 5.25s`.
Failing nodes: none.

#### Command 6.2.6 — Settings/factory/controlled-hybrid required matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_settings_product_recognizer_mode.py backend/tests/test_product_recognition_factory.py backend/tests/test_controlled_hybrid_product_recognition.py
```

Exit code: `0`.
Summary: `76 passed in 0.97s`.
Failing nodes: none.

#### Command 6.2.7 — Calibration CLI

Command (exact):
```
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output /private/tmp/phase-4-13-calibration.json --diagnose --diagnose-output /private/tmp/phase-4-13-calibration.diagnose.json --limit 47
```

Exit code: `0`.
Stdout (exact): `cases=47 policies=243 eligibility=not_eligible`.
Failing nodes: not applicable. The report eligibility failure is recorded in
§6.1.

#### Command 6.2.8 — Focused Phase-4 Ruff

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
```

Exit code: `0`.
Stdout: `All checks passed!`.
Findings: none.

#### Command 6.2.9 — Focused compileall

Command (exact):
```
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
```

Exit code: `0`. Stdout: empty (silent success).
Findings: none.

#### Command 6.2.10 — Strict OpenSpec validation

Command (exact):
```
openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict
```

Exit code: `0`.
Stdout (exact): `Change 'subphase-4-13-global-regression-debt-verification-phase-4-closure' is valid`.
Failing nodes: not applicable.

### 6.3 Optional-debt command matrix and baseline classification

#### Command 6.3.1 — Smoke (`api_smoke.py`)

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
```

Exit code: `1`.
Summary: `4 failed, 103 passed, 1 warning in 5.92s`.
Failing node IDs:

- `backend/tests/api_smoke.py::test_llm_settings_and_query_llm`
- `backend/tests/api_smoke.py::test_pending_context_execution`
- `backend/tests/api_smoke.py::test_pending_context_dispatcher`
- `backend/tests/api_smoke.py::test_agregar_producto_end_to_end`

Classification: **`verified_pre_existing`**. The result is exactly the four
historical smoke failures documented by the change; there is no fifth failure.
It is within the documented smoke baseline and does not block on this surface.

#### Command 6.3.2 — Ruff on `test_llm_settings.py`

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/tests/test_llm_settings.py
```

Exit code: `1`.
Findings: exactly three `B017` diagnostics, each with message
"Do not assert blind exception: `Exception`", at lines `28`, `120`, and `122`.

Classification: **`verified_pre_existing`**. This is exactly the documented
three-B017 baseline, with no additional finding or file spread; it does not
block on this surface.

#### Command 6.3.3 — Strict mypy on `product_recognizer.py`

Command (exact):
```
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
```

Exit code: `1`.
Summary: `Found 16 errors in 1 file (checked 1 source file)`.
All 16 findings are `[type-arg] Missing type arguments for generic type
"dict"`, at lines `72`, `245`, `342`, `343`, `391`, `467`, `471`, `479`,
`564`, `565`, `568`, `597`, `598`, `627`, `630`, and `631`.

Classification: **`verified_pre_existing`**. The inventory is exactly sixteen
historical `[type-arg]` findings; line-number drift is permitted by the
published baseline rule and no additional diagnostic category is present. It
does not block on this surface.

### 6.4 Diff and strict validation evidence

#### Command 6.4.1 — `git diff --check`

Command (exact):
```
git diff --check
```

Exit code: `0`. Stdout: empty; no whitespace errors.

#### Command 6.4.2 — Strict OpenSpec validation after evidence append

Command (exact):
```
openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict
```

Exit code: `0`.
Stdout (exact): `Change 'subphase-4-13-global-regression-debt-verification-phase-4-closure' is valid`.

### 6.5 Full validation matrix and closure result

| Surface | Result | Blocks? |
| --- | --- | --- |
| Fuzzy required matrix | 30 passed, 48 subtests; exit 0 | no |
| Vector/embedding required matrix | 92 passed, 58 subtests; exit 0 | no |
| Shadow required matrix | 55 passed, 54 subtests; exit 0 | no |
| Calibration required pytest matrix | 207 passed, 15 subtests; exit 0 | no |
| Pending selection/ambiguity required matrix | 105 passed, 29 subtests; exit 0 | no |
| Settings/factory/controlled-hybrid required matrix | 76 passed; exit 0 | no |
| Calibration CLI process | exit 0 | no by process status |
| Calibration report eligibility | `not_eligible`; reason `latency_budget_failed` | **yes** |
| Focused Phase-4 Ruff | 0 findings; exit 0 | no |
| Focused compileall | exit 0 | no |
| Optional smoke debt | exactly 4 historical failures | no |
| Optional `test_llm_settings.py` Ruff debt | exactly 3 historical B017 findings | no |
| Optional strict mypy debt | exactly 16 historical `[type-arg]` findings | no |
| `git diff --check` | exit 0 | no |
| Strict OpenSpec validation | valid; exit 0 | no |

Factual closure result: **DO NOT close Phase 4.** The required test suites and
static checks pass, and every optional-debt result is within its documented
baseline. However, the required calibration report is not eligible:
`eligibility.status` is `"not_eligible"`, with
`eligibility.reasons=["latency_budget_failed"]` and hybrid p95 latency
`748.3454998582602 ms` against the documented `500 ms` budget. The acceptance
condition requiring an eligible calibration report therefore fails and blocks
closure. No fix is implemented; the observation is recorded only.

### 6.6 Scope and operation confirmation

Repository file edited in this re-verification: **only**
`openspec/changes/subphase-4-13-global-regression-debt-verification-phase-4-closure/tasks.md`, by appending this section. The existing dirty worktree was
preserved. The calibration and diagnostic JSON files were written only under
`/private/tmp/` by the documented CLI command. No application code, tests,
fixtures, datasets, settings, migrations, specifications outside this change,
or archived changes were modified. No OpenSpec sync, archive, commit, or Phase-4
closure action occurred.

## 7. Re-verification evidence (post semantic-LLM availability)

This section is appended after the user reported that the semantic LLM is now
functional. Sections 1–6 remain historical evidence and are not overwritten.
The user's scope for this iteration is restricted to: the four named smoke
node IDs, the exact calibration CLI from `design.md` §"Validation design",
inspection of `/private/tmp/phase-4-13-calibration.json`, `openspec validate
... --strict`, and `git diff --check`. The full Phase-4 required matrix from
§6 was not re-executed in this iteration per the user's instruction. The
repository HEAD at the start of this re-verification was
`628e65bcd532159384681c0a4f356013a7ba972b` on `main`; the pre-existing dirty
worktree was preserved intact. Python 3.14.6 from `venv/bin/` was the executable
for every command.

### 7.1 Smoke subset (the four documented historical failures)

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py::test_llm_settings_and_query_llm backend/tests/api_smoke.py::test_pending_context_execution backend/tests/api_smoke.py::test_pending_context_dispatcher backend/tests/api_smoke.py::test_agregar_producto_end_to_end
```

Exit code: `1`.
Pytest summary: `4 failed in 3.37s`.

Failing node IDs (exact):
- `backend/tests/api_smoke.py::test_llm_settings_and_query_llm`
- `backend/tests/api_smoke.py::test_pending_context_execution`
- `backend/tests/api_smoke.py::test_pending_context_dispatcher`
- `backend/tests/api_smoke.py::test_agregar_producto_end_to_end`

Comparison with the documented four-failure baseline (`proposal.md` §"Known
debt and closure decision", and prior §4.1 / §5.3.1 / §6.3.1 evidence):
**unchanged**. The four failing node IDs are exactly the four archived
4.8/4.12A baseline cases by name. There is no fifth failure (the
`test_product_selection_context_resolver` regression recorded in §4.1
remains absent — it was already resolved in §5/§6). Per `design.md` Decision
table, the exact documented baseline does not block closure. This surface
remains `verified_pre_existing`.

### 7.2 Calibration CLI report inspection

Command (exact):
```
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output /private/tmp/phase-4-13-calibration.json --diagnose --diagnose-output /private/tmp/phase-4-13-calibration.diagnose.json --limit 47
```

Exit code: `0`.
Stdout (exact): `cases=47 policies=243 eligibility=eligible`.

`/private/tmp/phase-4-13-calibration.json` mtime: `Aug 6 10:53 2026`
(rewritten by this CLI run).

After the CLI completed, `/private/tmp/phase-4-13-calibration.json` was
inspected programmatically
(`python3 -c "import json; ..."`). The required fields are:

- `eligibility.status`: **`"eligible"`**.
- `eligibility.reasons`: **`[]`** (no blocking reason).
- `case_count`: **`47`**.
- `policy_count`: **`243`**.
- Latency metrics present in the report:
  - `latency_p50`: **`143.45683390274644` ms**.
  - `latency_p95`: **`241.80433340370655` ms**.
  - `hybrid_metrics.latency_p50`: `143.45683390274644` ms.
  - `hybrid_metrics.latency_p95`: `241.80433340370655` ms.
  - Dataset `latency_budget_ms_p95`: `500` ms (recorded in §6.1; the
    `p95 = 241.80 ms` value is well below this budget).
- `infrastructure_failures`: `6`.
- `failed_case_ids`: `c1-colloquial-coca`, `c1-alias-fugazza`,
  `c1-colloquial-coca-cola`, `c1-restricted-cuatro-quesos`,
  `c1-quantity-empanada-carne`, `c1-canonical-fugazzeta`.
- `mismatch_category_counts`: `total=2`,
  `real_fuzzy_recognizer_failure=2`, all other categories `0`.
- `hybrid_metrics.decision_accuracy`: `45/47 = 0.9574...`.
- `hybrid_metrics.top_1_accuracy`: `36/36 = 1.0`.
- `hybrid_metrics.presentation_resolution_accuracy`:
  `45/47 = 0.9574...`.
- `dataset_fingerprint`: `cc5c7f149916830984392578f07575efc250ffe5e920762179f1ab657b980cab`.
- `dataset_version`: `3`.

Comparison with the §6.1 baseline: the prior §6 run reported
`eligibility.status = "not_eligible"` with
`eligibility.reasons = ["latency_budget_failed"]`,
`hybrid_metrics.latency_p95 = 748.3454998582602 ms`, and
`infrastructure_failures = 6`. The current run reports
`eligibility.status = "eligible"` with
`eligibility.reasons = []`, `latency_p95 = 241.80433340370655 ms`,
and the same `infrastructure_failures = 6`. The eligibility reclassification
is the direct consequence of the semantic LLM becoming functional: the
hybrid `latency_p95` dropped from `748.34 ms` to `241.80 ms`, comfortably
inside the `500 ms` budget. The frozen `failed_case_ids` list and
`mismatch_category_counts` (`real_fuzzy_recognizer_failure = 2`, matching
the documented `known_fuzzy_limitation` baseline) are unchanged.

**Calibration eligibility result: PASS.** The acceptance condition
`eligibility.status == "eligible"` from `design.md` §"Acceptance criteria"
item 1 is satisfied. The previous §6 blocker
(`latency_budget_failed`) no longer reproduces and is **not** a
calibration eligibility blocker in this iteration.

### 7.3 `openspec validate ... --strict`

Command (exact):
```
openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict
```

Exit code: `0`.
Stdout (exact): `Change 'subphase-4-13-global-regression-debt-verification-phase-4-closure' is valid`.

### 7.4 `git diff --check`

Command (exact):
```
git diff --check
```

Exit code: `0`. Stdout: empty; no whitespace errors.

### 7.5 Classification of every observed deviation in this iteration

| Source | Observation | Class | Blocks? |
| --- | --- | --- | --- |
| Command 7.1 (smoke subset) | 4 failures, exactly the documented 4.8/4.12A baseline cases | `verified_pre_existing` | no |
| Command 7.2 (calibration CLI process) | exit 0 | passes | no |
| Command 7.2 (calibration report eligibility) | `eligible`; reasons `[]`; latency p95 `241.80 ms` vs `500 ms` budget | passes | no |
| Command 7.3 (`openspec validate --strict`) | valid; exit 0 | passes | no |
| Command 7.4 (`git diff --check`) | exit 0 | passes | no |
| Environment | Python 3.14.6 / venv, no environment blockers | not a regression | n/a |

No new required regression was introduced in the surfaces re-verified in this
iteration. The calibration eligibility blocker recorded in §6 (latency
budget exceeded) does not reproduce under the now-functional semantic LLM.

### 7.6 Factual closure recommendation (constrained to this iteration's scope)

The user's explicit instruction for this iteration is: "A factual closure
recommendation. Do not recommend closure unless the calibration result is
eligible and no new required regression exists." Within the scope of this
iteration (the four smoke node IDs, the calibration CLI, OpenSpec strict
validation, and `git diff --check`):

- Calibration result is **eligible** (§7.2). No blocking reason is present.
  The hybrid `latency_p95` is `241.80 ms`, below the `500 ms` budget. The
  frozen `failed_case_ids` list and `mismatch_category_counts` are unchanged
  relative to §6.
- No new required regression exists on the re-verified surfaces (§7.5).
  The four smoke failures match the archived 4-case baseline by exact name;
  the calibration report is eligible; OpenSpec strict validation passes;
  `git diff --check` passes.

The acceptance criteria in `design.md` §"Acceptance criteria" item 1 require
**every** required command (including the full Phase-4 regression surface from
§2.1–§2.7) to exit zero AND the calibration JSON to report
`eligibility.status == "eligible"`. The full Phase-4 required matrix was
**not** re-executed in this iteration per the user's scope restriction; the
prior §6 evidence recorded that matrix as fully green except for the
calibration eligibility block, which has now cleared. Combining this
iteration's evidence with §6 (which itself followed the
`subphase-4-13-2-restore-pending-descriptor-narrowing` corrective change
that fixed the pending-matrix regression noted in §5.6), the calibration
blocker that prevented Phase-4 closure recommendation in §6 is removed.

**Factual recommendation: the calibration eligibility blocker from §6 has
cleared under the now-functional semantic LLM, and no new required
regression was introduced in this iteration's scope. A final closure
recommendation is appropriate subject to the user re-running the full
required matrix from `design.md` if they want to reconfirm the remaining
required Phase-4 surfaces alongside this calibration result before issuing
explicit Phase-4 closure approval. No sync, archive, commit, or Phase-4
closure action is performed in this iteration.**

### 7.7 Scope and operation confirmation

Repository file edited in this re-verification: **only**
`openspec/changes/subphase-4-13-global-regression-debt-verification-phase-4-closure/tasks.md`, by appending this section. Sections 1–6 remain preserved
as historical evidence. The existing dirty worktree (`git status --short`
unchanged relative to the start of this iteration; `git rev-parse HEAD`
still `628e65bcd532159384681c0a4f356013a7ba972b` on `main`) was preserved
intact. The calibration and diagnostic JSON files were written only under
`/private/tmp/` by the documented CLI command. No application code, tests,
fixtures, datasets, settings, migrations, specifications outside this
change, archived changes, or unrelated dirty files were modified. No
OpenSpec sync, archive, commit, or Phase-4 closure action occurred.
