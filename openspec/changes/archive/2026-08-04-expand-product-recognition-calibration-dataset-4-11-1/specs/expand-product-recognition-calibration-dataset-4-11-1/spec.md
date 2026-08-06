# Capability: expand-product-recognition-calibration-dataset-4-11-1

## Purpose

Make the Subphase 4.11 offline calibration statistically useful for `comercio_id=1` by expanding the dataset with real database-backed cases covering the 80/20 of representative input shapes, and let the dataset carry the explicit eligibility inputs so the runner can emit a real `eligible` / `not_eligible` / `pending` verdict for Subphase 4.12 without operator-injected inputs.

## Requirements

### Requirement: Expanded calibration dataset for comercio_id=1

The system SHALL provide a versioned deterministic calibration dataset at `backend/data/product_recognition_calibration_cases.json` (`schema_version: 3`) that includes the ten preserved Subphase 4.11 cases and approximately 30–50 additional cases for `comercio_id=1`. The expanded dataset SHALL cover each of the following input shapes at least once:

- exact canonical product name;
- alias or colloquial wording;
- fuzzy misspelling;
- product plus presentation;
- explicit quantity word;
- ambiguous request (multiple presentations or products);
- unknown product;
- restricted candidate set;
- semantically similar product that may match fuzzy or vector;
- case where fuzzy and vector may disagree.

The expanded dataset SHALL reference only `producto_presentacion_id` values that exist in the database for `comercio_id=1` at the time the dataset is validated. New cases SHALL use `catalog_scope: "commerce_dynamic_database"` and an empty `catalogs[*].entries` list so the runner resolves the catalog from the database at runtime. The expanded dataset SHALL use `expected_producto_presentacion_id_ref` and a top-level `seed_refs` map for every new case whose expected ID is resolved from the database.

The first ten cases SHALL remain unchanged in `case_id`, `input_text`, `catalog_fixture`, `catalog_scope`, `expected_decision`, `allowed_candidate_ids`, `restricted_candidate_ids`, `match_expectation`, `presentation_resolution_expectation`, and `category`. The dataset SHALL contain no production customer data.

#### Scenario: Preserved baseline cases are unchanged

- **WHEN** the expanded dataset is validated
- **THEN** every preserved Subphase 4.11 `case_id` is present exactly once
- **AND** its `input_text`, `catalog_fixture`, `catalog_scope`, `expected_decision`, allowed and restricted candidate IDs, match expectation, presentation expectation, and category are unchanged

#### Scenario: Input shapes are covered

- **WHEN** the expanded dataset is validated
- **THEN** every required input shape category has at least one case for `comercio_id=1`
- **AND** every category in `{"canonical", "alias", "ambiguous", "unknown", "restricted", "commerce_isolation", "baseline"}` is present at least once across the new cases

#### Scenario: Referenced database IDs are valid

- **WHEN** the expanded dataset is validated against the seeded database
- **THEN** every `allowed_candidate_ids` entry and every `expected_producto_presentacion_id_ref` resolution exists in the database for `comercio_id=1`
- **AND** the validation fails fast with a stable error naming the missing ID and the offending case

#### Scenario: New cases use commerce dynamic database scope

- **WHEN** a new case has `id_comercio: 1`
- **THEN** its `catalog_scope` is `"commerce_dynamic_database"`
- **AND** its `catalogs[*].entries` list is empty
- **AND** its expected ID is resolved from the `seed_refs` map at runtime

### Requirement: Dataset carries optional eligibility inputs

The system SHALL allow the calibration dataset to carry an optional top-level `eligibility` block with the following fields:

- `primary_metric`: one of `"decision_accuracy"`, `"top_1_accuracy"`, `"canonical_match_accuracy"`, `"alias_match_accuracy"`, or `"restricted_candidate_accuracy"`;
- `required_improvement`: non-negative finite number;
- `false_positive_tolerance`: non-negative finite number in `[0, 1]`;
- `latency_budget_ms_p95`: non-negative finite number of milliseconds.

When the `eligibility` block is present, every field SHALL be present and valid. When the block is absent, the dataset SHALL remain valid and the runner SHALL fall back to the existing `pending` eligibility behaviour.

#### Scenario: Valid eligibility block is accepted

- **WHEN** the dataset carries an `eligibility` block with `primary_metric`, `required_improvement`, `false_positive_tolerance`, and `latency_budget_ms_p95` set to valid values
- **THEN** validation succeeds
- **AND** the runner consumes the block when no explicit `eligibility` argument is supplied

#### Scenario: Malformed eligibility block is rejected

- **WHEN** the dataset carries an `eligibility` block with a missing key, a non-numeric value, a negative `latency_budget_ms_p95`, an unsupported `primary_metric`, an `out-of-range` `false_positive_tolerance`, or a non-finite number
- **THEN** validation fails with a deterministic error naming the offending field and case

#### Scenario: Absent eligibility block keeps existing pending behaviour

- **WHEN** the dataset carries no `eligibility` block
- **THEN** validation succeeds
- **AND** the runner emits `eligibility.status == "pending"` with the documented missing-input reasons

### Requirement: Schema version three is accepted

The system SHALL accept calibration datasets with `schema_version` equal to `3`. The system SHALL continue to accept `schema_version` `1` and `2` with unchanged validation behaviour. No previous `schema_version` SHALL be removed from the validator.

#### Scenario: Schema version three is valid

- **WHEN** a dataset carries `schema_version: 3`
- **THEN** validation succeeds when every other invariant is satisfied
- **AND** the runner reports `dataset_version: 3` in the calibration report

#### Scenario: Schema version two remains valid

- **WHEN** a dataset carries `schema_version: 2`
- **THEN** validation succeeds with the existing 4.11 invariants
- **AND** the runner reports `dataset_version: 2` in the calibration report
