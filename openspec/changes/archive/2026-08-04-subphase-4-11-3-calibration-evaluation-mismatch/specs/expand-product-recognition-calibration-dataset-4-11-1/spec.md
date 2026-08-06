## ADDED Requirements

### Requirement: Targeted dataset corrections preserve invariants

When the Subphase 4.11.3 diagnostic classifies a case under `invalid_dataset_expectation`, `stale_seed_reference`, `commerce_scope_mismatch`, `product_id_mismatch`, `presentation_id_mismatch`, `output_normalization_mismatch`, or `decision_mapping_mismatch`, the dataset MAY be corrected for that case only when the diagnostic provides evidence that the expectation or seed reference is wrong against the current `comercio_id=1` catalog. The correction SHALL:

- leave the 11 preserved Subphase 4.11 cases (`schema_version: 2` baseline) untouched in `case_id`, `input_text`, `catalog_fixture`, `catalog_scope`, `expected_decision`, `allowed_candidate_ids`, `restricted_candidate_ids`, `match_expectation`, `presentation_resolution_expectation`, and `category`;
- keep `schema_version: 3`;
- keep every other case whose diagnostic did not flag an expectation / seed mismatch untouched;
- preserve the 11 + 36 case count (or grow only when a previously-misclassified case is corrected by changing its `expected_decision` from `unknown` to `unique` or `ambiguous` and the evidence proves the catalog supports it; the new case count SHALL be the minimum required for the documented coverage rule).

The dataset SHALL NOT weaken the coverage rule (every required input shape at least once; every category in `{canonical, alias, ambiguous, unknown, restricted, commerce_isolation, baseline}` at least once across the new cases; at least 30 evaluable `comercio_id=1` cases). The dataset SHALL NOT relax any `allowed_candidate_ids` to remove a previously-restricted ID, SHALL NOT delete a case merely to lift metrics, and SHALL NOT raise the `required_improvement` or `false_positive_tolerance` thresholds in the optional `eligibility` block.

Each corrected case SHALL carry an optional `correction_evidence` object containing `mismatch_category` (one of the ten documented categories from `calibration-evaluation-mismatch-diagnosis`), `reason` (a human-readable explanation of the demonstrated defect), and `catalog_reference` (the catalog artifact — a `seed_refs` key, a numeric `producto_presentacion.id`, or a comparable identifier — that supports the correction). Uncorrected cases, including all 11 preserved Subphase 4.11 cases, SHALL NOT carry a `correction_evidence` field. The dataset validator SHALL accept the optional `correction_evidence` object without rejecting uncorrected cases. JSON comments SHALL NOT be used.

#### Scenario: Corrected case preserves category coverage and shape coverage

- **WHEN** a Subphase 4.11.1 case is corrected as a result of a documented diagnostic
- **THEN** the 11 preserved Subphase 4.11 cases remain unchanged
- **AND** every category in `{canonical, alias, ambiguous, unknown, restricted, commerce_isolation, baseline}` is still present at least once across the dataset
- **AND** every required input shape is still covered at least once
- **AND** at least 30 `comercio_id=1` cases are still evaluable

#### Scenario: Corrected expectation is backed by catalog evidence

- **WHEN** a case's `expected_decision`, `expected_producto_presentacion_id_ref`, `allowed_candidate_ids`, `restricted_candidate_ids`, `match_expectation`, or `presentation_resolution_expectation` is changed
- **THEN** the change is accompanied by a documented diagnostic that proves the catalog supports the new expectation
- **AND** the case entry carries a `correction_evidence` object whose `mismatch_category`, `reason`, and `catalog_reference` document the correction
- **AND** the new values resolve against the current `comercio_id=1` database through the canonical `seed_refs` inventory
- **AND** the dataset validator reports no missing or cross-commerce references
- **AND** the dataset file uses no JSON comments to express the evidence

### Requirement: Inventory regeneration after seed_refs corrections

After any `seed_refs` correction, the runner SHALL regenerate the calibration dataset inventory and validate it against the current `comercio_id=1` database. The regeneration SHALL be the same `validate_dataset` + inventory step documented in Subphase 4.11.1, and SHALL use the same opaque symbolic `seed_refs` keys (no raw numeric IDs as portable references). The new inventory SHALL be committed to the calibration change root and SHALL be referenced by the dataset's `inventory_ref` path.

The runner SHALL refuse to run a calibration against a dataset whose `seed_refs` resolves to a missing or cross-commerce ID, and SHALL refuse to run a calibration whose inventory step has not been regenerated after the most recent `seed_refs` change.

#### Scenario: Inventory is regenerated after seed_refs correction

- **WHEN** a case's `expected_producto_presentacion_id_ref` value or any `seed_refs` key is changed
- **THEN** the inventory step is regenerated from the current `comercio_id=1` database
- **AND** the inventory records every `seed_refs` entry with the resolved numeric `producto_presentacion.id`, `producto.id`, `presentacion.id`, and `id_comercio`
- **AND** the dataset validator rejects any `seed_refs` entry that resolves to a missing or cross-commerce ID

#### Scenario: Runner refuses stale inventory

- **WHEN** the runner is invoked with a dataset whose `seed_refs` has changed since the last inventory commit
- **THEN** the runner fails closed with a deterministic error naming the offending `seed_refs` key
- **AND** the calibration report is not emitted
- **AND** the CLI returns non-zero

### Requirement: Canonical identifier mapping in the dataset

The dataset SHALL carry, for every `catalog_scope: "commerce_dynamic_database"` case, a single canonical identifier mapping that the runner uses to compare expectations against recognizer results. The mapping SHALL resolve to a numeric `producto_presentacion.id` and SHALL NOT carry parallel `presentacion_codigo` / `presentacion_descripcion` / `presentacion.id` strings that the runner could compare against. The dataset SHALL NOT define a case that compares against `presentacion.codigo` or `presentacion.descripcion` directly.

The 11 preserved Subphase 4.11 cases carry `catalog_scope: "in_memory"` and embedded `catalogs[*].entries`; their canonical identifier is the numeric `producto_presentacion.id` declared in the embedded catalog entry, and the Subphase 4.11.3 dataset corrections SHALL NOT change this contract.

#### Scenario: Database-backed cases carry a single canonical identifier

- **WHEN** a case has `catalog_scope: "commerce_dynamic_database"` and an `expected_producto_presentacion_id_ref`
- **THEN** the resolved value is the numeric `producto_presentacion.id`
- **AND** no other string or numeric representation of the same presentation is included in the dataset for that case
- **AND** the runner compares only against this numeric `producto_presentacion.id`

#### Scenario: In-memory cases continue to use embedded catalog IDs

- **WHEN** a case has `catalog_scope: "in_memory"` and embedded `catalogs[*].entries`
- **THEN** the canonical identifier is the numeric `producto_presentacion.id` declared in the embedded entry
- **AND** the dataset does not add a parallel `presentacion_codigo`/description mapping for the same case
