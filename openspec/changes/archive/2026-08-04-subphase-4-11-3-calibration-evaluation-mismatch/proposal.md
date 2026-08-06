## Why

The current calibration report under `schema_version: 3` reports only **0.1282** fuzzy decision accuracy and **0.1538** hybrid decision accuracy across 39 evaluated cases for `comercio_id=1`, with **34/36** fuzzy false unknowns and **12/36** hybrid false unknowns. The Subphase 4.12 verdict is `not_eligible` formally because of `latency_budget_failed`, but the dominant functional problem is that legitimate calibration cases are being scored as unknown or ambiguous before hybrid activation can ever be considered. We must diagnose whether the root cause sits in dataset expectations, catalog references, result normalization, decision mapping, presentation matching, or actual recognizer behavior, and apply the smallest robust correction that does not weaken the dataset merely to lift metrics.

## What Changes

- Add a deterministic per-case diagnostic command (`python -m backend.cli.calibrate_product_recognizer --diagnose`) that, for each evaluated case, emits `case_id`, input text, category, shape, expected decision, expected product & presentation IDs, actual fuzzy decision & candidates, actual hybrid decision & candidates, normalized IDs used by the evaluator, presentation-resolution result, and the exact mismatch reason.
- Introduce a closed mismatch-category taxonomy so every incorrect case is filed under exactly one of: `invalid_dataset_expectation`, `stale_seed_reference`, `commerce_scope_mismatch`, `product_id_mismatch`, `presentation_id_mismatch`, `output_normalization_mismatch`, `decision_mapping_mismatch`, `real_fuzzy_recognizer_failure`, `real_hybrid_recognizer_failure`, or `other_with_evidence`.
- Audit every current False Unknown / Incorrect Ambiguous against the taxonomy and attach evidence-backed diagnoses to the report.
- Correct only demonstrated defects in `dataset expectations`, `inventory generation`, `seed_refs`, `calibration runner`, `normalization`, `evaluator`, or `report aggregation`. Do not redesign the recognizer or change thresholds unless diagnostics prove an actual recognizer defect that cannot be fixed elsewhere.
- Store correction evidence for any corrected dataset case in an optional `correction_evidence` object attached to the case entry, containing `mismatch_category`, `reason`, and `catalog_reference`; uncorrected cases (including all 11 preserved Subphase 4.11 cases) SHALL NOT carry the field, and the dataset's `schema_version` SHALL remain `3`.
- Use one canonical identifier consistently for presentation resolution (the project's actual `producto_presentacion.id`, not `presentacion_codigo` / `presentacion.id` / normalized description) and stop silent dual-id comparisons.
- Regenerate and validate the calibration dataset inventory if any `seed_refs` or database-backed expectations change.
- Add focused regression coverage for each demonstrated mismatch category fixed.
- Re-run the full calibration and produce a new report from the documented command.
- Record Subphase 4.11.3 in the project roadmap and update the existing `### Implement Subphase 4.11.3 — …` pending entry to the proper completed entry.

## Capabilities

### New Capabilities

- `calibration-evaluation-mismatch-diagnosis`: Defines the closed mismatch-category taxonomy, the diagnostic CLI surface, the per-case evidence report schema, and the contract that the calibration runner can be invoked in a deterministic `--diagnose` mode without weakening any existing 4.11 / 4.11.1 requirement.

### Modified Capabilities

- `calibrate-hybrid-product-recognition-4-11`: The runner, evaluator, normalization, and report aggregation must use the canonical presentation identifier consistently, must classify each incorrect case into the taxonomy, and must preserve every pre-existing Subphase 4.11 invariant (fuzzy baseline preservation, frozen policy, bounded grid, denominated metrics, eligibility gates, atomic JSON report, CLI session ownership). The diagnostic output becomes a documented runner mode alongside the existing report.
- `expand-product-recognition-calibration-dataset-4-11-1`: The dataset may need targeted corrections to `expected_producto_presentacion_id_ref`, `allowed_candidate_ids`, `restricted_candidate_ids`, `seed_refs`, `match_expectation`, `presentation_resolution_expectation`, or `expected_decision` for cases where the diagnostic proves the expectation is wrong, while leaving the 11 preserved Subphase 4.11 cases and every other case untouched. `schema_version` remains `3`. Each corrected case SHALL carry an optional `correction_evidence` object (containing `mismatch_category`, `reason`, and `catalog_reference`); uncorrected cases SHALL NOT carry the field.

## Impact

- Affects `backend/cli/calibrate_product_recognizer.py`, the calibration runner, normalizer, evaluator, JSON report schema, and per-case mismatch-category emission.
- May touch `backend/data/product_recognition_calibration_cases.json` and its inventory generator for proven-stale `seed_refs` / expectations only.
- New focused tests in `backend/tests/test_product_recognition_calibration_4_11_3.py` (or similar) for the diagnostic mode, the taxonomy, the canonical-identifier consistency, and each demonstrated mismatch category.
- Update `openspec/specs/project.md` to replace the pending `### Implement Subphase 4.11.3 — …` entry with the proper `### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [x] — completed` entry.
- No API, persistence, dependency, embedding, Ollama, vector-search, runtime recognizer mode, recognizer factory, shadow authority, handler, resolver, pending context, intent, order, response, HTTP contract, or order transaction semantics changes are intended. `PRODUCT_RECOGNIZER_MODE=hybrid` remains inactive.
- No changes to embedding model `all-minilm:latest`, vector dimensions, stored embeddings, or latency budget.
- Hybrid mode is not activated regardless of the report.
