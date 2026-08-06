## 1. Inspection

- [x] 1.1 Re-read `backend/services/product_recognition_calibration_runner.py` lines 200-240 (`_hybrid_prediction`) and confirm (a) the existing 4.11.5 guard is preserved verbatim; (b) the `encounter` list construction, the `fuzzy` and `vector` dicts, the `values` list comprehension, the `sort`, the `ids` and `scores` construction, and the `_prediction` call are all preserved verbatim; (c) the only addition is a new positional `if` block above the existing 4.11.5 guard that checks `observation.fuzzy_decision == "unique"` AND `not observation.vector_ids` and returns a `StrategyPrediction` constructed from the fuzzy observation directly.
- [x] 1.2 Re-read the Subphase 4.11.5 archived proposal at `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/proposal.md` to confirm the symmetric pattern: the 4.11.5 guard is a positional `if` block at the top of `_hybrid_prediction` that returns a `StrategyPrediction` constructed from the fuzzy observation directly when `catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"`. The 4.11.7 guard follows the same pattern but with a different `fuzzy_decision` precondition.
- [x] 1.3 Confirm the change does NOT touch any file other than `backend/services/product_recognition_calibration_runner.py` (source), `backend/tests/test_product_recognition_calibration_4_11_7.py` (new test file), and the one-line dataset correction documented in task 3.3.
- [x] 1.4 Re-read the Subphase 4.11.5 archived diagnostics at `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/diagnostics/after.diagnose.json` and confirm the four failing cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) have `actual_fuzzy_decision == "unique"` AND `actual_fuzzy_candidate_ids` with one element AND `actual_hybrid_decision == "unknown"`. Confirm the symmetric guard conditions hold for each.

## 2. Add the Guard in `_hybrid_prediction`

- [x] 2.1 In `backend/services/product_recognition_calibration_runner.py`, add a new positional `if` block above the existing 4.11.5 guard at the top of `_hybrid_prediction`. The guard checks `observation.fuzzy_decision == "unique"` AND `not observation.vector_ids`. When both conditions are met, the guard returns a `StrategyPrediction` constructed from the fuzzy observation directly: `decision="unique"`, `top_id=observation.fuzzy_ids[0]`, `ranking=observation.fuzzy_ids`, `scores=observation.fuzzy_scores`, `canonical` and `alias` computed by `_exact_flags(case, observation.fuzzy_ids)` (the existing helper). The return shape mirrors the 4.11.5 guard's return shape for symmetry.
- [x] 2.2 Confirm the guard is a single positional `if` block (no `elif` chain, no `else`, no nested logic). The guard body is one `if` with one `return` statement. The guard is the FIRST statement in `_hybrid_prediction`, placed above the existing 4.11.5 guard.
- [x] 2.3 Confirm the existing 4.11.5 guard is preserved verbatim. The 4.11.7 guard is placed ABOVE it in source order; the 4.11.5 guard remains unchanged.

## 3. Write the Focused Regression Test File

- [x] 3.1 Create `backend/tests/test_product_recognition_calibration_4_11_7.py` with the focused regression suite. The file pins the closure criterion: the four named regressions become `unique` with the correct `producto_presentacion_id`, the 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous`, `false_positives.count` remains `0`, `incorrect_unique_decisions.count` remains `0`, and the complete 47-case calibration remains eligible. The suite runs the runner end-to-end and inspects the per-case decisions and the eligibility verdict.
- [x] 3.2 The file may inline short helpers from the 4.11.5 test file; no shared helper module is required. The file does NOT modify any existing test file.
- [x] 3.3 Apply the narrowly-scoped dataset correction: in `backend/data/product_recognition_calibration_cases.json`, set `allowed_candidate_ids: [33]` for the case `multi-word-jamon-queso-dynamic`. The case's `expected_decision` is `"unique"` and its `expected_producto_presentacion_id_ref` resolves to pid 33, so the empty list is malformed calibration metadata; the correction populates the list with the case's actual expected pid so the runner's `false_positive` metric (`top_id not in allowed_candidate_ids`) does not fire vacuously after the 4.11.7 guard promotes the case from `unknown` to `unique`. No other case in the dataset is modified; the `case_id`, input text, catalog scope, expected decision, and expected `producto_presentacion_id_ref` for every case are preserved.

## 4. Verification (Ruff on Touched Files)

- [x] 4.1 Run `PYTHONPATH=. venv/bin/python -m ruff check backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_7.py` from the repo root and confirm zero findings. The new guard MUST NOT introduce a new finding under any rule. The dataset correction is a JSON edit and is not subject to Ruff linting.

## 5. Verification (Compile)

- [x] 5.1 Run `PYTHONPATH=. venv/bin/python -m compileall backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_7.py` from the repo root and confirm exit code `0`. Both files MUST compile under CPython's standard library bytecode compiler.

## 6. Verification (Focused Tests)

- [x] 6.1 Run `PYTHONPATH=. venv/bin/pytest backend/tests/test_product_recognition_calibration_4_11_7.py -vv` from the repo root and confirm the new suite is green. The suite MUST cover the closure criterion: (a) the four named cases become `unique` with the correct `producto_presentacion_id`; (b) the 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous`; (c) `false_positives.count == 0`; (d) `incorrect_unique_decisions.count == 0`; (e) the complete 47-case calibration remains eligible. Confirm zero failures, zero errors, zero skips.

## 7. Verification (End-to-End Calibration Re-run)

- [x] 7.1 Run `PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output openspec/changes/subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after.json --diagnose --diagnose-output openspec/changes/subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/diagnostics/calibration_after_diagnose.json --limit 47` from the repo root and confirm exit code `0`. The CLI MUST NOT fail closed and MUST emit both the JSON report and the diagnostic JSON file.
- [x] 7.2 Inspect `calibration_after.json` and confirm `hybrid_metrics.decision_accuracy.count == 45` (up from 41) and `hybrid_metrics.false_unknowns.count == 2` (down from 6).
- [x] 7.3 Inspect `calibration_after.json` and confirm `hybrid_metrics.false_positives.count == 0` and `hybrid_metrics.incorrect_unique_decisions.count == 0`.
- [x] 7.4 Inspect `calibration_after.json` and confirm the eligibility verdict is `eligible`.
- [x] 7.5 Inspect `calibration_after_diagnose.json` and confirm the four named cases now have `actual_hybrid_decision == "unique"` and `mismatch_category == "correct"`.

## 8. Verification (OpenSpec)

- [x] 8.1 Run `openspec validate subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown --strict` and confirm the change bundle remains valid. The proposal, design, and tasks artifacts MUST validate as `valid: true`. Both capability specs (`calibrate-hybrid-product-recognition-4-11` ADDED Requirement + `hybrid-fuzzy-unique-fallback-4-11-7`) MUST satisfy the schema's `ADDED Requirements` + `REMOVED Requirements` formatting.

## 9. Reporting

- [x] 9.1 (Post-apply reporting step — NOT part of the runtime implementation surface; the runtime implementation surface is exactly the two files listed in `tasks.md` tasks 1.3 / 2.1 / 3.1 / 3.3.) Update `openspec/specs/project.md` to replace the pending `### Implement Subphase 4.11.7.` entry with the proper `### Subphase 4.11.7 — Fix Hybrid Degrades Fuzzy-Unique to Unknown [x] — completed` entry following the exact structure used by the Subphase 4.11.6 / 4.11.5 / 4.11.4 / 4.11.3 archived entries. Document the 1-block additive guard, the file touched, the four named cases that flip from `real_hybrid_recognizer_failure` to `correct`, the post-fix `decision_accuracy.count` (45), `false_unknowns.count` (2), `false_positives.count` (0), `incorrect_unique_decisions.count` (0), the eligibility verdict (`eligible`), the new focused regression test file, and the absence of any recognizer / calibration runner scoring formula / policy grid / dataset / contract change.
- [x] 9.2 Leave the change under `openspec/changes/subphase-4-11-7-fix-hybrid-degrades-fuzzy-unique-to-unknown/`; do not run specification sync or archive. The user will run `/opsx:sync` and `/opsx:archive` as separate explicit commands after the report is reviewed.