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

### Requirement: Dataset may carry an optional commerce_catalog_inventory and commerce_catalog_fingerprint

The calibration dataset MAY carry two optional top-level blocks alongside the existing `seed_refs` map and `inventory_fingerprint`:

- `commerce_catalog_inventory`: `dict[str, list[CatalogEntry]]` keyed by the string representation of `id_comercio`. Each list is the full runtime-compatible commerce catalog — all commerce-scoped `producto_presentacion` entries returned by the real runtime catalog assembly for `id_comercio` (active and inactive alike, with all four runtime availability flags preserved exactly), with the documented runtime field set (`producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `producto_activo`, `presentacion_activo`, `disponible`). Entries are deterministically sorted by `producto_presentacion_id` ascending. No inactive or unavailable entry is filtered out.
- `commerce_catalog_fingerprint`: `dict[str, str]` keyed by the string representation of `id_comercio`. Each value is the SHA-256 fingerprint (lowercase hex) of the canonical JSON of the corresponding `commerce_catalog_inventory[<key>]`, computed with sorted object keys, stable list order, and finite JSON values. This block is **reproducible evidence** of the database snapshot the change was authored against; the runner compares the freshly loaded DB catalog's fingerprint against this value at calibration time. The persisted inventory is NEVER the runtime source of truth for the catalog handed to the recognizer.

The existing `seed_refs` map, the existing `inventory_fingerprint` derivation (`backend/services/product_recognition_calibration_runner.py:612-628`), the existing stale-`seed_refs` guard, the `correction_evidence` schema, and the optional `eligibility` block are unchanged. The `inventory_fingerprint` and `commerce_catalog_fingerprint` are independent signals: `inventory_fingerprint` covers `seed_refs`; `commerce_catalog_fingerprint[<id_comercio>]` is the snapshot fingerprint of the full commerce catalog used to detect drift against the live database.

The blocks SHALL NOT bump `schema_version`. The 11 preserved `catalog_scope: "in_memory"` Subphase 4.11 cases SHALL NOT be touched. The 36 expanded `commerce_dynamic_database` cases SHALL NOT be touched. The 11 + 36 case count, the category coverage rule, the input-shape coverage rule, the at-least-30-evaluable-cases rule, and the optional `eligibility` block SHALL NOT change.

The blocks SHALL be regenerated by `python -m backend.scripts.calibration_inventory --mode regenerate-commerce-catalog --commerce-id <id>` against the current `<id_comercio>` database. Regeneration SHALL be idempotent: running it twice against an unchanged database SHALL produce byte-identical `commerce_catalog_inventory[<id_comercio>]` lists and `commerce_catalog_fingerprint[<id_comercio>]` strings. The regenerated blocks SHALL be committed under the change root alongside the dataset.

`validate_dataset` SHALL accept the optional blocks on `schema_version: 3` datasets without rejecting legacy datasets that omit them. The validator SHALL also continue to refuse an empty `commerce_catalog_inventory` block for a commerce that the dataset references — the per-commerce list, when present, MUST contain at least one commerce-scoped entry.

#### Scenario: commerce_catalog_inventory round-trips through regenerate-commerce-catalog

- **WHEN** `python -m backend.scripts.calibration_inventory --mode regenerate-commerce-catalog --commerce-id 1 --dataset backend/data/product_recognition_calibration_cases.json` is invoked against the current `comercio_id=1` database
- **THEN** the dataset's `commerce_catalog_inventory["1"]` contains every commerce-scoped `producto_presentacion` entry returned by the real runtime catalog assembly for `comercio_id == 1` (active and inactive alike)
- **AND** every entry carries the documented runtime field set
- **AND** entries are sorted by `producto_presentacion_id` ascending
- **AND** the dataset's `commerce_catalog_fingerprint["1"]` is the SHA-256 fingerprint of the canonical JSON of that list
- **AND** the existing `seed_refs` map and the `inventory_fingerprint` are unchanged
- **AND** the persisted blocks are reproducible evidence only; the runner loads the fresh DB catalog at calibration time and compares against `commerce_catalog_fingerprint["1"]`

#### Scenario: Backward compatibility for datasets without commerce_catalog_inventory or commerce_catalog_fingerprint

- **WHEN** a `schema_version: 3` dataset omits `commerce_catalog_inventory` and `commerce_catalog_fingerprint`
- **THEN** `validate_dataset` accepts the dataset
- **AND** the runner fails closed with `StaleCommerceCatalogError` naming the offending `id_comercio` when it visits any commerce, because the persisted `commerce_catalog_fingerprint[<id_comercio>]` is required for the drift check
- **AND** no regression is introduced for legacy `schema_version` `1` and `2` datasets (the runner fails closed at the same point, which is the correct behavior given the missing snapshot evidence)

#### Scenario: Idempotent regeneration

- **WHEN** the `regenerate-commerce-catalog` step is run twice against the same database with no intervening changes
- **THEN** `commerce_catalog_inventory["1"]` is byte-identical between the two runs
- **AND** `commerce_catalog_fingerprint["1"]` is byte-identical between the two runs
- **AND** every entry is sorted and deduped deterministically

#### Scenario: Existing seed_refs and inventory_fingerprint are unchanged

- **WHEN** the dataset carries `seed_refs`, `inventory_fingerprint`, `commerce_catalog_inventory`, and `commerce_catalog_fingerprint`
- **THEN** the `inventory_fingerprint` derived from `seed_refs` is unchanged by the addition of the new blocks
- **AND** the runner's stale-`seed_refs` refusal at `runner.py:612-628` continues to compare against the unchanged fingerprint derivation
- **AND** the `commerce_catalog_fingerprint` refusal is independent: at calibration time the runner computes the fresh DB catalog's fingerprint and compares it against `commerce_catalog_fingerprint[<id_comercio>]` (not against `commerce_catalog_inventory[<id_comercio>]`), failing closed with `StaleCommerceCatalogError` on mismatch

#### Scenario: Correction evidence is not affected

- **WHEN** a corrected case carries the optional `correction_evidence` object documented in Subphase 4.11.3
- **THEN** the `correction_evidence` shape is unchanged
- **AND** uncorrected cases (including all 11 preserved Subphase 4.11 cases) SHALL NOT carry `correction_evidence`
- **AND** the `validate_dataset` validator accepts `correction_evidence` without requiring `commerce_catalog_inventory`

#### Scenario: Inactive and unavailable entries remain present in the commerce_catalog_inventory with their original flags

- **WHEN** the database has an inactive or unavailable `producto_presentacion` row for `comercio_id == 1` (any of `activo`, `producto_activo`, `presentacion_activo`, `disponible` is `false`)
- **THEN** the corresponding entry remains in `commerce_catalog_inventory["1"]` and is not filtered out
- **AND** the entry's four runtime availability-flag fields (`activo`, `producto_activo`, `presentacion_activo`, `disponible`) carry the documented boolean values verbatim
- **AND** the recognizer's existing `disponibles` / `encontrados_no_disponibles` split classifies the entry as expected at recognition time (matching unavailable entries under `encontrados_no_disponibles`; matching available entries under `disponibles`)

#### Scenario: Cross-commerce entries are absent

- **WHEN** the database has `producto_presentacion` rows for `comercio_id == 2`
- **THEN** those rows are NOT present in `commerce_catalog_inventory["1"]`
- **AND** those rows are present in `commerce_catalog_inventory["2"]`
- **AND** `commerce_catalog_fingerprint["1"]` and `commerce_catalog_fingerprint["2"]` differ whenever the per-commerce lists differ
