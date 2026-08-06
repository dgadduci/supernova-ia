# Capability: calibration-evaluation-mismatch-diagnosis

## Purpose

TBD

## Requirements

### Requirement: Closed mismatch-category taxonomy

The system SHALL classify every incorrect calibration case into exactly one of the following stable, lowercase snake-case categories:

- `invalid_dataset_expectation`: the dataset's `expected_decision`, `expected_producto_presentacion_id_ref`, `allowed_candidate_ids`, `restricted_candidate_ids`, `match_expectation`, or `presentation_resolution_expectation` is wrong against the current `comercio_id=1` catalog.
- `stale_seed_reference`: a `seed_refs` entry resolves to a `producto_presentacion.id` that no longer exists in the database, links to a deleted presentation row, or resolves to a row whose presentation catalog has changed.
- `commerce_scope_mismatch`: the runner or evaluator used a `producto_presentacion.id` whose `id_comercio` differs from the case's `id_comercio`, or the case's vector query used a different `id_comercio` than the case declares.
- `product_id_mismatch`: the runner compared the case's expected `producto_presentacion.id` against the recognizer's selected `producto_presentacion.id` for a different `producto.id` while the underlying product identity was unchanged.
- `presentation_id_mismatch`: the runner compared the case's expected `producto_presentacion.id` against a `producto_presentacion.id` whose `id_presentacion` differs from the expected one, while the product identity was correct.
- `output_normalization_mismatch`: the recognizer returned a valid `producto_presentacion.id` but the runner or evaluator coerced it to `None`, a different `int`, a representation, or a code-string before comparison.
- `decision_mapping_mismatch`: the runner mapped a recognizer result into `unique` / `ambiguous` / `unknown` in a way that contradicts the documented decision-mapping rules, even though the underlying recognizer output was correct.
- `real_fuzzy_recognizer_failure`: the fuzzy recognizer did not return the expected candidate for a case whose dataset expectation, seed reference, commerce scope, IDs, normalization, and decision mapping are all correct.
- `real_hybrid_recognizer_failure`: the hybrid recognizer did not return the expected candidate while the fuzzy ground truth was correct, attributable to the observational hybrid scoring or strategy logic.
- `other_with_evidence`: a single category documented inline with the concrete evidence that did not fit any of the above.

The system SHALL emit the category per incorrect case in the diagnostic report and SHALL emit a `mismatch_category_counts` object in the calibration JSON report with one count per category. Categories are exhaustive — every incorrect case MUST be filed under exactly one of the ten categories. Categories with zero incorrect cases SHALL remain at zero; the diagnostic SHALL NOT fabricate or force examples merely to populate empty categories. `correct` cases SHALL NOT be counted in `mismatch_category_counts`.

#### Scenario: Every incorrect case is filed under exactly one category

- **WHEN** the calibration run completes and produces incorrect cases
- **THEN** the diagnostic report contains exactly one `mismatch_category` value per incorrect case
- **AND** each value is one of the ten documented categories
- **AND** `mismatch_category_counts` in the JSON report sums to the total number of incorrect cases
- **AND** `correct` cases are not included in `mismatch_category_counts`
- **AND** categories with zero incorrect cases are reported as zero rather than being omitted

#### Scenario: `other_with_evidence` requires explicit evidence

- **WHEN** a case is filed under `other_with_evidence`
- **THEN** the diagnostic entry contains a non-empty `evidence` string naming the concrete mismatch
- **AND** the evidence string is preserved verbatim in the JSON report entry for that case

### Requirement: Diagnostic command and per-case evidence report

The system SHALL expose a deterministic `--diagnose` mode on `python -m backend.cli.calibrate_product_recognizer` that, for each evaluated case, emits the following fields in a stable order:

- `case_id`
- `input_text`
- `category`
- `shape` (one of: `canonical`, `alias`, `fuzzy_misspelling`, `product_plus_presentation`, `quantity_word`, `ambiguous`, `unknown`, `restricted`, `semantically_similar`, `fuzzy_vector_disagreement`, `commerce_isolation`, `baseline`)
- `expected_decision`
- `expected_producto_presentacion_id` (resolved numeric `producto_presentacion.id`, or `null`)
- `expected_presentacion_id` (resolved numeric `presentacion.id`, or `null`)
- `actual_fuzzy_decision`
- `actual_fuzzy_producto_presentacion_id` (or `null`)
- `actual_fuzzy_presentacion_id` (or `null`)
- `actual_fuzzy_candidate_ids` (numeric `producto_presentacion.id` list, ordered)
- `actual_hybrid_decision`
- `actual_hybrid_producto_presentacion_id` (or `null`)
- `actual_hybrid_presentacion_id` (or `null`)
- `actual_hybrid_candidate_ids` (numeric `producto_presentacion.id` list, ordered)
- `normalized_id_used_by_evaluator` (numeric `producto_presentacion.id`, or `null`)
- `presentation_resolution_result` (`correct`, `incorrect`, `not_applicable`, or `error`)
- `mismatch_category` (one of the ten categories above, or `correct` if the case was scored correctly)
- `evidence` (non-empty string when `mismatch_category` is `other_with_evidence`, otherwise empty)

The CLI SHALL write the diagnostic report atomically to the path supplied by `--diagnose-output` (default `<output>.diagnose.json`), keep the existing JSON report at `--output`, and SHALL NOT change any other Subphase 4.11 / 4.11.1 CLI behaviour. The CLI SHALL return non-zero only on the same fatal conditions as the existing mode (invalid dataset, invalid configuration, database failure, or total calibration failure).

#### Scenario: Diagnostic mode emits stable per-case fields

- **WHEN** the CLI is invoked with `--diagnose` and a valid dataset
- **THEN** the diagnostic output file exists and parses as strict JSON
- **AND** every case yields exactly one entry with the documented fields in the documented order
- **AND** the existing JSON report is still written when `--output` is supplied
- **AND** the CLI exit code matches the existing mode's documented fatal-failure rules

#### Scenario: Diagnostic output is deterministic for fixed inputs

- **WHEN** the CLI is invoked twice with the same dataset, dataset fingerprint, embeddings, and policies
- **THEN** the diagnostic output files are byte-identical
- **AND** sorted object keys, stable list order, and finite JSON values are used

### Requirement: Diagnostic mode preserves existing Subphase 4.11 and 4.11.1 invariants

The `--diagnose` mode SHALL NOT weaken any of the following Subphase 4.11 or 4.11.1 invariants:

- fuzzy executes exactly once per case per policy set;
- vector search executes at most once per case at the largest requested top-k;
- commerce and candidate boundaries are preserved;
- infrastructure failures are sanitized and recorded;
- the deterministic Cartesian grid is unchanged;
- explicitly denominated metrics are unchanged;
- the eligibility gates from Subphase 4.11 and Subphase 4.11.1 are unchanged;
- the JSON report schema is unchanged modulo the new `mismatch_category_counts` field;
- the dataset carries `schema_version: 3` and continues to accept `1` and `2`;
- the 11 preserved Subphase 4.11 cases remain untouched in `case_id`, `input_text`, `catalog_fixture`, `catalog_scope`, `expected_decision`, `allowed_candidate_ids`, `restricted_candidate_ids`, `match_expectation`, `presentation_resolution_expectation`, and `category`.

#### Scenario: Diagnostic mode does not weaken existing requirements

- **WHEN** the CLI runs in `--diagnose` mode against the existing `schema_version: 3` dataset
- **THEN** the existing Subphase 4.11 and 4.11.1 test suites continue to pass without modification
- **AND** the existing JSON report contents (`selected_policy`, `fuzzy_metrics`, `vector_metrics`, `hybrid_metrics`, `absolute_difference`, `infra_failures`, `failed_cases`, `latency_p50`, `latency_p95`, per-category metrics, eligibility) remain byte-identical modulo the new `mismatch_category_counts` field and per-case `mismatch_category` field
- **AND** the 11 preserved Subphase 4.11 cases are unchanged in the dataset
