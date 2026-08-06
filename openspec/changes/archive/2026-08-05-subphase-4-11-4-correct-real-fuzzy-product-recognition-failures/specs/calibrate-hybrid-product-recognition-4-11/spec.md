## ADDED Requirements

### Requirement: Calibration runner loads the full-commerce catalog once per calibration run and reuses it for every case at the same commerce

The runner SHALL load the full runtime-compatible commerce catalog from PostgreSQL for each `id_comercio` it encounters at most once per calibration run. The freshly loaded DB catalog is the runtime source of truth; the persisted `commerce_catalog_inventory` block (when present) is reproducible evidence of the database snapshot the change was authored against and is NEVER handed to the recognizer. The same fresh DB catalog object SHALL be reused for every `catalog_scope: "commerce_dynamic_database"` case at that commerce, in both the observation step and the prediction step. The runner SHALL NOT issue a catalog query per case, per call, or per recognizer invocation; the per-commerce fresh DB catalog is cached on `self._commerce_catalog_cache` for the duration of the run.

The catalog handed to the fuzzy recognizer SHALL be the full runtime-compatible commerce catalog for the case's `id_comercio` — every commerce-scoped `producto_presentacion` entry returned by the real runtime catalog assembly (active and inactive alike, with all four runtime availability flags preserved), sorted by `producto_presentacion_id` ascending. The runner SHALL NOT consult `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_decision`, `expected_producto_presentacion_id`, `expected_producto_presentacion_id_ref`, any availability flag, or any other expected label when assembling the catalog. The catalog is determined solely by `id_comercio` and the real runtime catalog assembly.

The 11 preserved `catalog_scope: "in_memory"` Subphase 4.11 cases SHALL continue to use their embedded `catalogs[*].entries` and SHALL NOT consume the per-commerce catalog.

`allowed_candidate_ids` and `restricted_candidate_ids` SHALL be applied strictly in the evaluator, after the fuzzy recognizer returns its candidates. The evaluator accepts a candidate as in-boundary iff its `producto_presentacion.id` is in `allowed_candidate_ids`, and flags a candidate as a boundary violation iff its id is in `restricted_candidate_ids`. The vector-search boundary check at `runner.py:654-660` (allowed candidates filtered by `set(case["allowed_candidate_ids"])`) is unchanged.

The deterministic Cartesian grid, the explicitly denominated metrics, the eligibility gates, the JSON report schema (modulo documented new fields), the existing CLI flags (`--dataset`, `--output`, `--diagnose`, `--diagnose-output`, `--commerce-id`, `--limit`), and the Subphase 4.11.3 diagnostic surface (`mismatch_category`, `mismatch_category_counts`, per-case diagnostic JSON) are unchanged.

#### Scenario: commerce_dynamic_database case receives the fresh DB catalog

- **WHEN** the runner evaluates a `commerce_dynamic_database` case with `id_comercio == 1` and the fresh DB catalog for commerce `1` contains 80 entries
- **THEN** the fuzzy recognizer is invoked with a catalog that contains exactly those 80 entries
- **AND** the entries are sorted by `producto_presentacion_id` ascending
- **AND** the catalog is byte-identical to the catalog handed to every other `id_comercio == 1` case in the same run
- **AND** the catalog handed to the recognizer is the fresh DB catalog — not the persisted `commerce_catalog_inventory`, even when both contain the same entries

#### Scenario: Catalog is loaded once per commerce, not once per case

- **WHEN** the runner evaluates 36 `commerce_dynamic_database` cases at `id_comercio == 1`
- **THEN** the catalog is loaded exactly once for `id_comercio == 1`
- **AND** the same cached catalog object is reused for all 36 cases
- **AND** no catalog query or load happens between cases
- **AND** the runner's catalog-cache counter reports `1` for `id_comercio == 1` and `0` for any commerce the runner did not visit

#### Scenario: Catalog is independent of allowed_candidate_ids

- **WHEN** two `commerce_dynamic_database` cases at `id_comercio == 1` have different `allowed_candidate_ids`
- **THEN** both cases receive the same catalog
- **AND** `allowed_candidate_ids` is consumed only by the evaluator after recognition
- **AND** the catalog is byte-identical between the two cases

#### Scenario: Catalog is independent of expected_producto_presentacion_id

- **WHEN** two `commerce_dynamic_database` cases at `id_comercio == 1` have different `expected_producto_presentacion_id`
- **THEN** both cases receive the same catalog
- **AND** `expected_producto_presentacion_id` is consumed only by the evaluator
- **AND** the catalog is byte-identical between the two cases

#### Scenario: Restricted candidates remain in the catalog and are flagged by the evaluator

- **WHEN** a case has `restricted_candidate_ids = [9]` and the recognizer returns id `9` as a candidate
- **THEN** id `9` is present in the catalog passed to the recognizer
- **AND** the evaluator flags id `9` as a boundary violation after recognition
- **AND** the per-case mismatch category is recorded under the documented Subphase 4.11.3 taxonomy

#### Scenario: in_memory case is not touched by the per-commerce catalog

- **WHEN** the runner evaluates one of the 11 preserved `catalog_scope: "in_memory"` cases
- **THEN** the per-commerce catalog loader is skipped for that case
- **AND** the case's embedded `catalogs[*].entries` is passed to the fuzzy recognizer unchanged
- **AND** the Subphase 4.11 byte-identical re-runs for the 11 preserved cases remain byte-identical modulo the documented new `mismatch_category` and `mismatch_category_counts` fields
- **AND** the per-commerce catalog cache is not populated by an `in_memory` case

#### Scenario: Vector search boundary is unchanged

- **WHEN** the runner evaluates a `commerce_dynamic_database` case with `allowed_candidate_ids = [1, 9, 39]` and `restricted_candidate_ids = [9]`
- **THEN** the vector search is invoked with `candidate_producto_presentacion_ids=case["allowed_candidate_ids"]`
- **AND** the existing per-case `candidate_boundary_violation` failure category is preserved
- **AND** the per-commerce fuzzy catalog does not influence the vector-search boundary

#### Scenario: Catalog is deterministic for fixed inputs

- **WHEN** the runner is invoked twice against an unchanged PostgreSQL database with the same dataset
- **THEN** the per-commerce fresh DB catalogs loaded for both runs are byte-identical
- **AND** the observation step and the prediction step consume identical catalogs within a run
- **AND** the resulting JSON report and diagnostic file are byte-identical for equal recorded observations

#### Scenario: commerce_catalog_fingerprint refusal fails closed on stale catalog

- **WHEN** the runner is invoked and the freshly loaded DB catalog for `id_comercio == 1` has a fingerprint that does not match `commerce_catalog_fingerprint["1"]` in the dataset
- **THEN** the runner fails closed with `StaleCommerceCatalogError` naming the offending `id_comercio` and the expected / actual fingerprints
- **AND** the calibration report is not emitted
- **AND** the CLI returns non-zero
- **AND** the fresh DB catalog is NOT handed to the recognizer in this run

#### Scenario: commerce_catalog_fingerprint refusal fails closed when the persisted fingerprint is absent

- **WHEN** the runner is invoked with a dataset that omits `commerce_catalog_fingerprint["1"]` and the runner visits `id_comercio == 1`
- **THEN** the runner fails closed with `StaleCommerceCatalogError` naming the missing `id_comercio`
- **AND** the calibration report is not emitted
- **AND** the CLI returns non-zero

#### Scenario: Fresh DB catalog is the runtime source even when the persisted inventory matches

- **WHEN** the runner is invoked with a dataset whose `commerce_catalog_inventory["1"]` and `commerce_catalog_fingerprint["1"]` match the freshly loaded DB catalog for `id_comercio == 1`
- **THEN** the runner proceeds
- **AND** the catalog handed to the recognizer is the fresh DB catalog — NOT the persisted `commerce_catalog_inventory` (the persisted inventory is evidence only, never the runtime source)
- **AND** the runner's cache (`self._commerce_catalog_cache`) holds exactly one catalog object per visited commerce

#### Scenario: Existing CLI flags are unchanged

- **WHEN** the CLI is invoked with the same flags as in Subphase 4.11.3 (`--dataset`, `--output`, `--diagnose`, `--diagnose-output`, `--commerce-id`, `--limit`)
- **THEN** the existing exit-code semantics are preserved
- **AND** the JSON report is written to the same path
- **AND** the diagnostic JSON file is written to the same path
- **AND** no new flag is introduced
