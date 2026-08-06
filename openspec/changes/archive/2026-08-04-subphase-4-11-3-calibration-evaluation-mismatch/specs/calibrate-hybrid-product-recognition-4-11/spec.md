## ADDED Requirements

### Requirement: Canonical presentation identifier consistency

The runner, evaluator, and report aggregation SHALL resolve the canonical presentation identifier for a case to the numeric `producto_presentacion.id` (and, when required, the corresponding `presentacion.id`) consistently. The system SHALL NOT mix the following representations in the same comparison or normalization step:

- `producto_presentacion.id` (numeric primary key);
- `presentacion.id` (numeric primary key of the presentation catalog row);
- `presentacion.codigo` (short human-readable string, e.g. `UNIDAD`);
- `presentacion.descripcion` (free-text description);
- `presentacion_codigo` or `presentacion_descripcion` derived from the result row.

When the runner computes a presentation-resolution verdict, it SHALL compare the case's expected `producto_presentacion.id` against the recognizer's selected `producto_presentacion.id` and SHALL classify the verdict as `correct` only when both numeric IDs are equal. The runner SHALL NOT compare numeric IDs against `presentacion.codigo` strings, normalized descriptions, or presentation catalog IDs without an explicit one-to-one mapping derived from the catalog at runtime.

#### Scenario: Presentation verdict uses the canonical identifier

- **WHEN** a case has an expected `producto_presentacion.id` and the recognizer returns a candidate with the same `producto_presentacion.id` but a different `presentacion.codigo`
- **THEN** the runner records the presentation verdict as `correct` because the canonical numeric `producto_presentacion.id` matches
- **AND** the comparison does not silently compare against `presentacion.codigo` or `presentacion.descripcion`

#### Scenario: Mixed identifier representations are rejected

- **WHEN** the runner's normalization step receives a recognizer result whose selected `producto_presentacion.id` resolves to a different `presentacion.id` than the case's expected `producto_presentacion.id`
- **THEN** the runner classifies the case as `presentation_id_mismatch` under the Subphase 4.11.3 mismatch-category taxonomy
- **AND** does not coerce the numeric IDs into `presentacion.codigo` strings, description strings, or `presentacion_codigo` fields before comparison

#### Scenario: Canonical identifier is resolved from the seed_refs map

- **WHEN** a case has `catalog_scope: "commerce_dynamic_database"` and a `seed_refs` entry pointing to the expected `producto_presentacion.id`
- **THEN** the runner resolves the expected identifier to the numeric `producto_presentacion.id` returned by the canonical inventory step
- **AND** the runner does not compare against the `seed_refs` symbolic key, nor against any column other than `producto_presentacion.id`

### Requirement: Per-case mismatch category classification

The runner SHALL attach a `mismatch_category` to every case in the JSON report and the diagnostic output. The category SHALL be one of the ten documented in `calibration-evaluation-mismatch-diagnosis` (or `correct` when no mismatch is detected). The runner SHALL emit `mismatch_category_counts` in the JSON report with one count per category and a `total` count equal to the number of cases classified under the ten mismatch categories.

When a case fails the run (infrastructure failure, sanitized failure category), the runner SHALL still emit a `mismatch_category` of `real_fuzzy_recognizer_failure` or `real_hybrid_recognizer_failure` as appropriate, and SHALL NOT leave the field null.

#### Scenario: Every case has a mismatch_category

- **WHEN** the runner produces a JSON report
- **THEN** every case carries a `mismatch_category` field
- **AND** the field is a documented category value or `correct`
- **AND** `mismatch_category_counts` sums to the total number of incorrect cases

#### Scenario: Failed cases are still classified

- **WHEN** a case fails due to a sanitized infrastructure failure
- **THEN** the report classifies it under `real_fuzzy_recognizer_failure` or `real_hybrid_recognizer_failure` as appropriate
- **AND** the existing `infra_failures` and `failed_cases` fields are preserved unchanged

### Requirement: Diagnostic mode is part of the runner surface

The runner SHALL expose a `--diagnose` mode that writes the per-case evidence report described in `calibration-evaluation-mismatch-diagnosis` without modifying the existing JSON report schema beyond the new `mismatch_category` per case and `mismatch_category_counts` aggregate. The runner SHALL run the same dataset fingerprinting, fuzzy execution, vector search, hybrid ranking, eligibility gate, and JSON report emission as the existing mode; the diagnostic mode SHALL only add the per-case classification and the diagnostic evidence file.

The runner SHALL NOT bypass policy validation, fail closed on invalid datasets, or alter the existing metric denominators in diagnostic mode.

#### Scenario: Diagnostic mode reuses the existing runner pipeline

- **WHEN** the runner is invoked with `--diagnose`
- **THEN** fuzz, embedding, vector search, hybrid ranking, eligibility, and JSON report metrics are computed exactly as in the existing mode
- **AND** the only additional outputs are the per-case `mismatch_category` classification and the diagnostic evidence file
- **AND** the existing JSON report remains unchanged modulo the documented new fields

#### Scenario: Diagnostic mode is opt-in

- **WHEN** the runner is invoked without `--diagnose`
- **THEN** the diagnostic evidence file is not written
- **AND** the per-case `mismatch_category` field and the `mismatch_category_counts` aggregate are still emitted in the JSON report
- **AND** the existing CLI behaviour is otherwise preserved
