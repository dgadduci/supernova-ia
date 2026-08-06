## 1. Roadmap and Inspection

- [x] 1.1 Replace the pending `### Implement Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch. [ ]` line in `openspec/specs/project.md` with the proper `### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [ ]` pending entry (objective, context, scope, out-of-scope, files affected). Leave the implementation-step placeholder lines in the project roadmap so the completion task can replace them with the final report.
- [x] 1.2 Inspect the current calibration runner, evaluator, normalizer, JSON report emitter, CLI module, dataset validator, and `seed_refs` inventory code paths; record the exact callsites that compare `producto_presentacion.id` against `presentacion.codigo`, `presentacion.id`, or normalized descriptions, and identify the missing diagnostic surface.
- [x] 1.3 Capture the current calibration report metrics verbatim (fuzzy decision accuracy 0.1282, hybrid decision accuracy 0.1538, fuzzy false unknowns 34/36, hybrid false unknowns 12/36, hybrid incorrect ambiguities 21/22, hybrid presentation resolution 7/39, infra failures 0, eligibility `not_eligible` / `latency_budget_failed`) so the before/after comparison is anchored.

## 2. Mismatch Category Taxonomy

- [x] 2.1 Define a closed `MISMATCH_CATEGORY` enum (or `Final` string-constant set) with the ten documented categories: `invalid_dataset_expectation`, `stale_seed_reference`, `commerce_scope_mismatch`, `product_id_mismatch`, `presentation_id_mismatch`, `output_normalization_mismatch`, `decision_mapping_mismatch`, `real_fuzzy_recognizer_failure`, `real_hybrid_recognizer_failure`, `other_with_evidence`. Place it in a module the runner, evaluator, and report reader all import.
- [x] 2.2 Implement a pure `classify_mismatch(case_record, inventory_entry)` function that returns the first matching category in the documented evaluation order (commerce-scope → product-id → presentation-id → output-normalization → decision-mapping → dataset-expectation → seed-reference → real-fuzzy → real-hybrid → other-with-evidence). The function SHALL be a pure function of the case record and the resolved inventory entry; no new database calls.
- [x] 2.3 Add a focused unit test pinning the documented evaluation order on a synthetic case for each category.

## 3. Canonical Identifier Consistency

- [x] 3.1 Add a `normalize_canonical_id(record)` helper that resolves the canonical numeric `producto_presentacion.id` from a recognizer result row, an inventory entry, an expected seed reference, or a candidate list. The helper SHALL raise a deterministic error when the input is missing or references a different identifier kind (e.g. a `presentacion.codigo` string).
- [x] 3.2 Refactor every comparison site in the runner and evaluator that previously compared `producto_presentacion.id` against `presentacion.codigo`, `presentacion.id`, or normalized descriptions to call the new helper. Record each refactored callsite and the before/after behaviour.
- [x] 3.3 Add a focused regression test that constructs a recognizer result with a matching `producto_presentacion.id` but a different `presentacion.codigo` and asserts the runner records the presentation verdict as `correct`.

## 4. Diagnostic Mode

- [x] 4.1 Add `--diagnose` and `--diagnose-output` flags to `python -m backend.cli.calibrate_product_recognizer`. The flags SHALL be opt-in; the existing CLI behaviour is preserved when they are absent.
- [x] 4.2 Implement the per-case diagnostic record emitter that produces the documented fields in the documented stable order: `case_id`, `input_text`, `category`, `shape`, `expected_decision`, `expected_producto_presentacion_id`, `expected_presentacion_id`, `actual_fuzzy_decision`, `actual_fuzzy_producto_presentacion_id`, `actual_fuzzy_presentacion_id`, `actual_fuzzy_candidate_ids`, `actual_hybrid_decision`, `actual_hybrid_producto_presentacion_id`, `actual_hybrid_presentacion_id`, `actual_hybrid_candidate_ids`, `normalized_id_used_by_evaluator`, `presentation_resolution_result`, `mismatch_category`, and `evidence` (non-empty only when `mismatch_category` is `other_with_evidence`).
- [x] 4.3 Emit the `mismatch_category_counts` aggregate in the JSON report alongside the existing fields and the per-case `mismatch_category` field. The aggregate SHALL sum to the total incorrect cases.
- [x] 4.4 Write the diagnostic output file atomically to the path supplied by `--diagnose-output` (default `<output>.diagnose.json`) using the same atomic-write contract as the existing JSON report. The CLI SHALL preserve the existing exit-code rules (non-zero only on invalid dataset, invalid configuration, database failure, or total calibration failure).

## 5. Dataset Inventory Guard

- [x] 5.1 Add an `inventory_generated_at` field on the dataset (and a parallel `inventory_path` field if the inventory is checked into the change root) and persist the inventory under the change root.
- [x] 5.2 Make the runner refuse to run a calibration when the dataset's `seed_refs` has changed since the inventory was generated. The refusal SHALL emit a deterministic error naming the offending `seed_refs` key and return non-zero from the CLI.
- [x] 5.3 Add a focused regression test that mutates a dataset's `seed_refs` after the inventory is generated and asserts the runner fails closed with the documented error.

## 6. Run Baseline Diagnostic

- [x] 6.1 Run `python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output <change-root>/diagnostics-before.json --diagnose --diagnose-output <change-root>/diagnostics-before.diagnose.json` against the unchanged dataset and capture the per-case mismatch category counts.
- [x] 6.2 Bucket the diagnostic output into the ten categories and record the count per category, the top entry per category, and the candidate matches between the case's expected `producto_presentacion.id` and the actual recognizer candidates.
- [x] 6.3 Confirm that every incorrect case carries exactly one valid `mismatch_category` value drawn from the ten documented categories, that `mismatch_category_counts.total` equals the total number of incorrect cases, that `correct` cases are not counted as mismatches, and that categories with zero incorrect cases remain at zero (the diagnostic SHALL NOT fabricate or force examples merely to populate empty categories).

## 7. Targeted Dataset Corrections

- [x] 7.1 For each case flagged under `invalid_dataset_expectation`, `stale_seed_reference`, `commerce_scope_mismatch`, `product_id_mismatch`, `presentation_id_mismatch`, `output_normalization_mismatch`, or `decision_mapping_mismatch`, correct the dataset with explicit evidence recorded in an optional `correction_evidence` object attached to the corrected case entry. The object SHALL contain `mismatch_category` (one of the ten documented categories), `reason` (a human-readable explanation of the demonstrated defect), and `catalog_reference` (the catalog artifact — a `seed_refs` key, a numeric `producto_presentacion.id`, or a comparable identifier — that supports the correction). Uncorrected cases, including all 11 preserved Subphase 4.11 cases, SHALL NOT carry a `correction_evidence` field. The 11 preserved Subphase 4.11 cases SHALL NOT be touched.
- [x] 7.2 Verify that every correction preserves the 11 + 36 case count (or grows only when a previously-misclassified case is corrected by changing its `expected_decision` from `unknown` to `unique` or `ambiguous` and the catalog supports it), keeps `schema_version: 3`, keeps every category in `{canonical, alias, ambiguous, unknown, restricted, commerce_isolation, baseline}` present at least once, keeps every required input shape covered at least once, keeps at least 30 evaluable `comercio_id=1` cases, and adds a valid `correction_evidence` object on each corrected case (no JSON comments; uncorrected cases SHALL NOT carry the field).
- [x] 7.3 Run the dataset validator after every correction and confirm zero missing or cross-commerce references.

## 8. Inventory Regeneration and Final Calibration

- [x] 8.1 Regenerate the `seed_refs` inventory from the current `comercio_id=1` database using the same `validate_dataset` + `build_seed_refs_inventory` step documented in Subphase 4.11.1. Commit the regenerated inventory to the change root.
- [x] 8.2 Re-run the full calibration with `--diagnose` and commit the new JSON report and diagnostic evidence file under the change root. Document the exact command in the completion report.
- [x] 8.3 Confirm the new report's `mismatch_category_counts` aggregate is consistent with the diagnostic output file and that the eligibility verdict reflects the documented gates (the verdict may still be `not_eligible` for `latency_budget_failed`; the goal of this subphase is to make the functional categories correct, not to flip the verdict).

## 9. Focused Regression Tests

- [x] 9.1 Add `backend/tests/test_product_recognition_calibration_4_11_3.py` with focused tests for the diagnostic mode (atomic write, deterministic output, stable field order, preserved exit-code semantics); the mismatch-category taxonomy (closed set of categories, documented evaluation order, every incorrect case has exactly one valid category, `correct` cases are not counted as mismatches, `mismatch_category_counts.total` equals the total incorrect cases, categories with zero cases remain at zero, `other_with_evidence` requires non-empty evidence); the canonical-identifier helper (refuses non-canonical identifiers, returns the numeric `producto_presentacion.id`); the inventory-refusal path (fails closed on stale `seed_refs`); and each demonstrated mismatch category. Synthetic unit tests SHALL cover every taxonomy category individually so the closed set is verified, but the real-calibration-run tests SHALL NOT require every category to be populated in a single run.
- [x] 9.2 Confirm the existing Subphase 4.11 and 4.11.1 test suites remain green and the runner-import-graph is still clean of `backend.tests.*`, `backend.scripts.calibration_inventory`, and any fixture module.

## 10. Verification

- [x] 10.1 Run `PYTHONPATH=. venv/bin/pytest backend/tests/test_product_recognition_calibration_4_11_3.py -vv` and report the exact pass count.
- [x] 10.2 Run the focused Subphase 4.11 and 4.11.1 test suites and confirm zero regressions.
- [x] 10.3 Run `PYTHONPATH=. venv/bin/python -m ruff check` over every touched Python file and fix only failures introduced by this change.
- [x] 10.4 Run `PYTHONPATH=. venv/bin/python -m mypy --strict` over every touched production file and report any pre-existing unrelated failures separately.
- [x] 10.5 Run `PYTHONPATH=. venv/bin/python -m compileall` over every touched Python file and confirm exit 0.
- [x] 10.6 Run `openspec validate subphase-4-11-3-calibration-evaluation-mismatch --strict` and confirm the active change remains valid, unsynchronized, and unarchived.

## 11. Completion Report

- [x] 11.1 Report the root cause summary, mismatch count by category, files changed, tests added, before/after metrics, final eligibility status, remaining real recognizer failures, exact calibration command, and confirmation that hybrid runtime was not activated.
- [x] 11.2 Update `openspec/specs/project.md` to replace the pending `### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [ ]` entry with the proper `### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [x] — completed` entry following the exact structure used by Subphase 4.11.2.
- [x] 11.3 Leave the change under `openspec/changes/subphase-4-11-3-calibration-evaluation-mismatch/`; do not run specification sync or archive.
