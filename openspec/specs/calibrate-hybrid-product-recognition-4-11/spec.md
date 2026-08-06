# Capability: calibrate-hybrid-product-recognition-4-11

## Purpose

TBD

## Requirements

### Requirement: Deterministic calibration dataset

The system SHALL provide a versioned deterministic calibration dataset derived from the complete Subphase 4.1 product-recognizer baseline. Every existing baseline case SHALL retain its `case_id`, input semantics, catalog semantics, and expected outcome. The dataset SHALL add only representative cases for behavior not covered by the baseline.

Every calibration case SHALL contain `case_id`, `id_comercio`, input text, `expected_decision` with value `unique`, `ambiguous`, or `unknown`, nullable `expected_producto_presentacion_id`, `allowed_candidate_ids`, `restricted_candidate_ids`, canonical/alias expectation, presentation-resolution expectation, and metric category. Case IDs SHALL be unique. Candidate ID collections SHALL have stable order and no duplicates. Restricted IDs SHALL NOT occur in allowed IDs.

The dataset SHALL contain no production customer data. Its fingerprint SHALL be computed by the runner from canonical UTF-8 JSON with sorted object keys and stable array order. A fixed string SHALL NOT be described as a dataset fingerprint unless produced by that computation.

#### Scenario: Existing baseline cases are preserved

- **WHEN** the calibration dataset is validated
- **THEN** all Subphase 4.1 baseline case IDs are present exactly once
- **AND** their input, catalog semantics, and expected outcomes are unchanged
- **AND** the database-dependent baseline case has a deterministic seed reference and is not silently skipped

#### Scenario: Missing coverage is added minimally

- **WHEN** a baseline coverage audit finds no representative commerce-isolation or restricted-exclusion case
- **THEN** the dataset adds the smallest representative case set for the missing categories
- **AND** each added case uses approved fixture data rather than production data

#### Scenario: Dataset fingerprint is derived

- **WHEN** the runner loads a valid dataset
- **THEN** it computes the SHA-256 fingerprint from canonical dataset JSON
- **AND** the report carries the computed value

### Requirement: Typed hybrid decision policy

The system SHALL expose this frozen dataclass:

```python
@dataclass(frozen=True)
class HybridDecisionPolicy:
    fuzzy_weight: float
    vector_weight: float
    unique_threshold: float
    ambiguous_threshold: float
    minimum_score_gap: float
    vector_top_k: int
```

The policy SHALL reject non-finite numeric values; weights outside `[0, 1]`; weights that do not sum to `1` within the project-standard floating-point tolerance; thresholds or score gap outside `[0, 1]`; `unique_threshold < ambiguous_threshold`; and `vector_top_k <= 0`.

#### Scenario: Valid policy is frozen

- **WHEN** a policy satisfying every invariant is constructed
- **THEN** construction succeeds
- **AND** assigning to a field raises `dataclasses.FrozenInstanceError`

#### Scenario: Invalid policy is rejected

- **WHEN** any policy invariant is violated
- **THEN** policy construction raises a deterministic validation error before embedding or database work begins

### Requirement: Offline calibration runner

The system SHALL provide an offline calibration runner that, for each selected case, executes fuzzy exactly once, generates one query embedding, executes vector search for the case's `id_comercio`, preserves allowed and restricted candidate boundaries, calculates observational hybrid rankings, applies supplied policies, compares each strategy with the expected outcome, and collects metrics.

The runner SHALL execute vector retrieval once per case at the largest requested top-k and SHALL derive smaller policy top-k rankings without repeating embedding or vector calls. It SHALL continue after individual fuzzy, embedding, or vector failures, preserve sanitized failure categories and stable failed case IDs, and SHALL treat a run with no evaluable hybrid cases as total calibration failure.

The runner SHALL NOT call or modify the runtime recognizer factory, shadow authority, `PRODUCT_RECOGNIZER_MODE`, handlers, resolvers, pending contexts, intents, orders, responses, or persistence contracts. Fuzzy SHALL remain the authoritative runtime recognizer and hybrid SHALL remain observational.

#### Scenario: Fuzzy executes once per case

- **WHEN** multiple policies are evaluated for one case
- **THEN** the fuzzy recognizer is invoked exactly once for that case
- **AND** the query embedding and vector search are each invoked at most once

#### Scenario: Commerce and candidate boundaries are preserved

- **WHEN** a case has an `id_comercio`, allowed candidates, and restricted candidates
- **THEN** vector search uses that exact commerce ID and allowed-candidate boundary
- **AND** no fuzzy, vector, or hybrid result contains a restricted candidate
- **AND** a candidate from another commerce is treated as an isolation failure

#### Scenario: Infrastructure failure does not abort remaining cases

- **WHEN** embedding or vector search fails for one case
- **THEN** the runner records a sanitized failure category and case ID
- **AND** evaluates the fuzzy baseline for that case when available
- **AND** continues with subsequent cases
- **AND** does not include stack traces or raw exception text in the report

### Requirement: Bounded deterministic parameter search

The system SHALL generate a deterministic Cartesian grid containing these search points:

- fuzzy/vector weights: `(0.4, 0.6)`, `(0.5, 0.5)`, `(0.6, 0.4)`
- unique threshold: `0.65`, `0.70`, `0.75`
- ambiguous threshold: `0.35`, `0.40`, `0.45`
- minimum score gap: `0.00`, `0.05`, `0.10`
- vector top-k: `3`, `5`, `7`

The values SHALL be labeled as provisional search points, not calibrated outputs. Invalid combinations SHALL be rejected by policy validation and duplicates SHALL be removed while preserving declared order. The search SHALL use no external ML library, Bayesian optimization, genetic algorithm, or online learning.

Policies tied on the agreed primary metric SHALL be ordered by fewer false positives, fewer incorrect `unique` decisions, higher top-1 accuracy, fewer false unknowns, lower top-k, closest normalized Manhattan distance to the current provisional defaults, and finally declared grid order.

#### Scenario: Grid generation is repeatable

- **WHEN** the grid is generated repeatedly from the same definition
- **THEN** it produces equal policies in equal order
- **AND** the report carries the exact number evaluated

#### Scenario: Equal policies use deterministic tie-breaking

- **WHEN** two policies have equal primary-metric values
- **THEN** the documented tie-break sequence selects the same policy on every run

### Requirement: Explicitly denominated calibration metrics

The report SHALL include total cases, decision accuracy, top-1 accuracy, recall at top-k, false positives, false unknowns, incorrect unique decisions, correct and incorrect ambiguities, presentation-resolution accuracy, canonical-match accuracy, alias-match accuracy, restricted-candidate accuracy, fuzzy baseline accuracy, vector-only accuracy, hybrid accuracy, fuzzy/vector top-1 agreement, latency p50, latency p95, infrastructure failures, failed case IDs, selected policy, and per-category metrics.

Let `N` be all valid cases selected after filters; `N_id` cases with expected product-presentation ID; `N_presentation` cases whose presentation expectation is applicable; `N_canonical` canonical cases; `N_alias` alias cases; `N_restricted` restricted cases; and `N_category(c)` cases in category `c`. Infrastructure failures SHALL remain in applicable denominators. A zero denominator SHALL serialize as `null`.

The metrics SHALL use these denominators:

- decision, fuzzy baseline, vector-only, hybrid, false-positive, and infrastructure-failure rates: `N`;
- top-1 accuracy and recall at top-k: `N_id`;
- false-unknown rate: cases expected not-unknown;
- incorrect-unique rate: predicted-unique cases;
- correct-ambiguity rate: expected-ambiguous cases;
- incorrect-ambiguity rate: predicted-ambiguous cases;
- presentation-resolution accuracy: `N_presentation`;
- canonical-match accuracy: `N_canonical`;
- alias-match accuracy: `N_alias`;
- restricted-candidate accuracy: `N_restricted`;
- fuzzy/vector top-1 agreement: cases where both produced non-null top-1 IDs;
- per-category metrics: the same populations intersected with category `c`.

False positives SHALL count predicted-unique decisions when unique was not expected and expected-unique predictions whose unique ID is not allowed. Incorrect unique decisions SHALL count predicted-unique cases with non-unique expectation or wrong expected ID. False unknowns SHALL count predicted unknown when unknown was not expected. Correct ambiguities SHALL count expected ambiguous predicted ambiguous; incorrect ambiguities SHALL count predicted ambiguous when ambiguous was not expected.

Latency p50 and p95 SHALL use nearest-rank percentiles over attempted case durations: sort ascending, use one-based rank `ceil(p * count)`, and clamp to the available range.

#### Scenario: Failures cannot inflate accuracy

- **WHEN** an applicable case has an infrastructure failure
- **THEN** it remains in the strategy's applicable denominator
- **AND** it cannot count as a correct prediction

#### Scenario: Percentiles are deterministic for recorded samples

- **WHEN** fixed latency samples are supplied in any order
- **THEN** p50 and p95 equal the documented nearest-rank results

### Requirement: Fuzzy baseline comparison and eligibility

The final report SHALL compare rows containing `metric`, `fuzzy_baseline`, `selected_hybrid_policy`, and `absolute_difference` using identical populations.

Eligibility inputs SHALL explicitly provide the agreed primary metric, required improvement, false-positive tolerance, and latency budget. Restricted-candidate non-regression, exact canonical and alias preservation, and commerce isolation SHALL be mandatory gates. Missing configurable inputs SHALL produce eligibility `pending` and stable reasons naming each missing input. Complete inputs with any failed gate SHALL produce `not_eligible`; only complete inputs with every gate passing SHALL produce `eligible`.

The runner SHALL NOT invent a tolerance or mark a selected policy eligible merely because it is selected.

#### Scenario: Missing criteria keep eligibility pending

- **WHEN** any primary-metric, improvement, false-positive-tolerance, or latency-budget input is absent
- **THEN** eligibility is `pending`
- **AND** reasons identify every missing input

#### Scenario: Complete criteria gate 4.12 explicitly

- **WHEN** all eligibility inputs are present
- **THEN** eligibility is `eligible` only if the primary metric improves as required, false positives remain within tolerance, restricted-candidate performance does not regress, exact canonical and alias resolution are preserved, commerce isolation passes, and latency is within budget
- **AND** every failed gate appears as a stable reason when eligibility is `not_eligible`

### Requirement: Safe deterministic JSON report

The runner SHALL write a deterministic JSON calibration report containing dataset version and computed fingerprint, embedding model and dimension, number of cases, number of policies evaluated, selected policy, fuzzy metrics, vector metrics, hybrid metrics, absolute differences, infrastructure failures, failed cases, latency p50/p95, per-category metrics, Subphase 4.12 eligibility, and reasons when not eligible or pending.

Serialization SHALL use sorted object keys, stable list order, and finite JSON values. The report SHALL NOT include input text, vectors, credentials, prompts, source documents, stack traces, raw exception text, or production customer data.

#### Scenario: Report is machine-readable and safe

- **WHEN** calibration produces a report
- **THEN** strict JSON parsing succeeds
- **AND** repeated serialization of the same recorded observations is byte-identical
- **AND** forbidden sensitive fields and values are absent

### Requirement: Runner reads eligibility from dataset when no explicit argument is supplied

The runner SHALL accept an `eligibility` keyword argument on `ProductRecognitionCalibrationRunner.run` with the same semantics established in Subphase 4.11. When the `eligibility` argument is `None` and the validated dataset carries an optional top-level `eligibility` block, the runner SHALL use the dataset block as the eligibility input by mapping `latency_budget_ms_p95` to the `latency_budget` field consumed by the existing gate. When the `eligibility` argument is `None` and the dataset has no `eligibility` block, the runner SHALL fall back to the existing `pending` eligibility behaviour.

The dataset `eligibility` block SHALL be ignored when the caller supplies an explicit `eligibility` argument. The runner SHALL NOT invent a tolerance or mark a selected policy eligible merely because it is selected.

#### Scenario: Dataset eligibility is consumed when no explicit argument is supplied

- **WHEN** the dataset carries a valid `eligibility` block with `primary_metric`, `required_improvement`, `false_positive_tolerance`, and `latency_budget_ms_p95`
- **AND** `runner.run(dataset)` is called without an `eligibility` argument
- **THEN** the runner uses the dataset block as the eligibility input
- **AND** the emitted `eligibility.status` is `eligible`, `not_eligible`, or `pending` per the documented gates

#### Scenario: Explicit eligibility argument overrides the dataset block

- **WHEN** the dataset carries an `eligibility` block
- **AND** `runner.run(dataset, eligibility={...})` is called with an explicit `eligibility` argument
- **THEN** the runner uses the explicit argument
- **AND** the dataset block is ignored

#### Scenario: Absent eligibility block keeps existing pending behaviour

- **WHEN** the dataset carries no `eligibility` block
- **AND** `runner.run(dataset)` is called without an `eligibility` argument
- **THEN** the runner emits `eligibility.status == "pending"` with the documented missing-input reasons

### Requirement: Local calibration CLI

The system SHALL expose `python -m backend.cli.calibrate_product_recognizer` with `--dataset`, `--output`, `--commerce-id`, and `--limit` options. The CLI SHALL validate inputs, create and own one database session, close it in `finally`, write the JSON report atomically, and print a concise summary.

The CLI SHALL return non-zero for invalid dataset, invalid configuration, database failure, or total calibration failure. Individual embedding/vector failures with at least one evaluable hybrid case SHALL produce a partial report and SHALL NOT alone force non-zero. The CLI SHALL NOT modify `PRODUCT_RECOGNIZER_MODE` or commit database changes.

#### Scenario: CLI owns and closes its session

- **WHEN** the CLI succeeds or raises after session creation
- **THEN** its database session is closed exactly once
- **AND** no transaction is committed

#### Scenario: CLI reports fatal failures

- **WHEN** dataset validation, configuration, database access, or all hybrid evaluations fail
- **THEN** the CLI returns non-zero
- **AND** does not emit credentials, prompts, vectors, stack traces, or raw exception text

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

### Requirement: hybrid guard preserves fuzzy ambiguity for pending_product_selection_restricted cases (including category-level ambiguity)

The hybrid decision produced by the runner (`backend/services/product_recognition_calibration_runner.py`) SHALL return `"ambiguous"` when the case's `catalog_scope == "pending_product_selection_restricted"` AND the fuzzy decision is explicitly `ambiguous`. The fuzzy decision is `"ambiguous"` when EITHER (a) `len(fuzzy_ids) > 1` on the stored `CaseObservation.fuzzy_ids` (i.e. the fuzzy recognizer returned multiple product-level candidates via `encontrados` / `encontrados_posibles[].productos[]`), OR (b) the recognizer result contains a category-level `encontrados_posibles` group with `kind: "category"` detected by the `_fuzzy_decision(result)` helper. The guard is a single positional tag in the existing `_decision` path (or its equivalent in `_prediction` / `_hybrid_prediction`) that fires before the scoring rule consults `policy.fuzzy_weight`, `policy.vector_weight`, `policy.unique_threshold`, `policy.ambiguous_threshold`, `policy.minimum_score_gap`, `policy.vector_top_k`, the canonical/alias promotion in `_exact_flags`, the vector's top-1, or the score combination. The guard does not modify `_hybrid_prediction`'s scoring formula, the policy grid, the JSON report schema, the diagnostic surface, or the CLI surface.

The fuzzy decision is threaded into `_decision` (or its equivalent) as a derived parameter from the existing `CaseObservation.fuzzy_ids` and the category discriminator (computed once in `_hybrid_prediction` via `_fuzzy_decision(fuzzy_result)`, where `_fuzzy_decision(result)` returns `"ambiguous"` whenever a category-level `encontrados_posibles` group carries `kind: "category"`; otherwise it falls back to the existing id-based logic `"unique" if len(fuzzy_ids) == 1 else "ambiguous" if len(fuzzy_ids) > 1 else "unknown" if len(fuzzy_ids) == 0`). The guard SHALL inspect the fuzzy decision explicitly and SHALL NOT infer fuzzy ambiguity from the combined hybrid `ranking` — the combined hybrid ranking is the union of `observation.fuzzy_ids` and `observation.vector_ids`, so a fuzzy-`unique` + vector-`unique(other)` case produces a multi-candidate hybrid ranking even though the fuzzy was not ambiguous. Inferring fuzzy ambiguity from the combined hybrid `ranking` (e.g. via `len(ranking) > 1`) is unsafe and is explicitly forbidden by this requirement.

The guard fires only when both conditions are met:
- `case.get("catalog_scope") == "pending_product_selection_restricted"`
- the fuzzy decision is `"ambiguous"` (the direct evidence being EITHER `len(fuzzy_ids) > 1` on `CaseObservation.fuzzy_ids`, OR a category-level `encontrados_posibles` group with `kind: "category"` detected by `_fuzzy_decision(result)`)

The guard depends ONLY on `catalog_scope` and `fuzzy_decision`. Case origin (in-memory vs database) is irrelevant to the guard; `in_memory` is NOT a disabling condition; `commerce_dynamic_database` is NOT a disabling condition by origin alone. Cases of either origin remain unaffected unless both guard conditions are satisfied. The case `ambiguous-empanada-carne` IS an `in_memory` case (its catalog is loaded from the in-memory fixture `empanada_carne_restricted`) and the guard MUST fire for it because its `catalog_scope == "pending_product_selection_restricted"` AND its `fuzzy_decision == "ambiguous"`; the fact that the case is `in_memory` (uses an in-memory catalog fixture) is irrelevant to whether the guard fires. When the fuzzy returns exactly one candidate (or `unknown`), the guard does not fire — even if the combined hybrid ranking contains multiple candidates because the vector contributed an extra candidate. When the fuzzy returns `ambiguous` but the scope is not `pending_product_selection_restricted`, the guard does not fire. The guard is purely additive: it can only force `ambiguous`; it never promotes an otherwise-correct decision to `ambiguous`.

`_decision` SHALL also return `"ambiguous"` when the combined ranking is empty AND `fuzzy_decision == "ambiguous"` (category-level), and SHALL return `"unknown"` otherwise. This is a small refinement of the existing `if not ranking: return "unknown"` line; it does NOT alter the existing behavior for non-empty rankings, for `fuzzy_decision == "unique"`, or for `fuzzy_decision == "unknown"`. The runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`).

#### Scenario: fuzzy ambiguous + restricted pending scope => hybrid remains ambiguous

- **WHEN** the calibration runner evaluates the case `ambiguous-empanada-carne` (input `"empanada de carne"`, `catalog_scope: pending_product_selection_restricted`, `id_comercio: 4`, `allowed_candidate_ids: [11, 12]`, in-memory catalog `empanada_carne_restricted` with `pid=11` (`Empanada de Carne PICANTE`) and `pid=12` (`Empanada de Carne TRADICIONAL`), `expected_decision: ambiguous`)
- **AND** the fuzzy recognizer returns ambiguous with candidates `[11, 12]` (the in-memory catalog has both presentations and the user did not specify a presentation)
- **AND** the vector search returns `unique(pid=11)` (the vector picked the PICANTE presentation)
- **THEN** the fuzzy decision (derived from `observation.fuzzy_ids = (11, 12)` via `_fuzzy_decision(fuzzy_result)`) is `"ambiguous"`
- **AND** the guard fires (the scope is `pending_product_selection_restricted` AND the fuzzy decision is explicitly `ambiguous`)
- **AND** the hybrid decision is `ambiguous` regardless of the vector's top-1 contribution (the semantic/vector top-1 is NOT allowed to promote the case to `unique`)
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)
- **AND** the `false_positives.count` drops from `1` to `0`
- **AND** the `false_positive_tolerance_failed` eligibility reason is eliminated

#### Scenario: guard does not fire for commerce_dynamic_database cases

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case with `allowed_candidate_ids: [1, 2]`, `id_comercio: 1`, fuzzy returns ambiguous `[1, 2]`, vector returns `unique(pid=1)` (e.g. `c1-canonical-pizza-muzzarella`)
- **THEN** the catalog scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"ambiguous"`
- **AND** the guard does not fire (the scope check fails — the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`)
- **AND** the hybrid decision follows the existing scoring rule (the canonical/alias promotion fires and the decision is `unique`)
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns exactly one candidate

- **WHEN** the calibration runner evaluates a `pending_product_selection_restricted` case with fuzzy returning `unique(pid=11)` (e.g. a future refinement case where the fuzzy resolves the presentation)
- **THEN** the catalog scope is `pending_product_selection_restricted`
- **AND** `len(fuzzy_ids) == 1` (the fuzzy decision is explicitly `"unique"`, not `"ambiguous"`)
- **AND** the guard does not fire (the fuzzy decision check fails — the fuzzy decision is `"unique"`, not `"ambiguous"`; the guard does NOT inspect the combined hybrid `ranking` to infer fuzzy ambiguity)
- **AND** the hybrid decision follows the existing scoring rule

#### Scenario: guard does not fire when fuzzy returns unique BUT the combined hybrid ranking contains multiple candidates

- **WHEN** the calibration runner evaluates a `pending_product_selection_restricted` case where the fuzzy returns `unique(pid=11)` (i.e. `observation.fuzzy_ids = (11,)`) AND the vector returns a different candidate `unique(pid=12)` (i.e. `observation.vector_ids = (12,)`)
- **THEN** the catalog scope is `pending_product_selection_restricted`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"unique"` (NOT `ambiguous`)
- **AND** the combined hybrid `ranking` (the union of `observation.fuzzy_ids` and `observation.vector_ids`) contains 2 candidates `(11, 12)` with `len(ranking) > 1`
- **AND** the guard does NOT fire (the previous `len(ranking) > 1` proxy would have incorrectly fired; the corrected guard inspects the fuzzy decision explicitly and the fuzzy decision is `"unique"`, not `"ambiguous"`)
- **AND** the hybrid decision follows the existing scoring rule and is NOT forced to `ambiguous`
- **AND** the case is classified by the existing scoring rule (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns unknown

- **WHEN** the calibration runner evaluates the case `picante-restricted-refinement` (input `"picante"`, `catalog_scope: pending_product_selection_restricted`, `expected_decision: unknown`)
- **THEN** the fuzzy returns `unknown` (no candidates match the presentation refinement token)
- **AND** `len(fuzzy_ids) == 0`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"unknown"` (NOT `ambiguous`)
- **AND** the guard does not fire (the fuzzy decision check fails — the fuzzy decision is `"unknown"`, not `"ambiguous"`)
- **AND** the hybrid decision is `unknown` (matching the existing scoring rule)
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns category-level ambiguity at the wrong scope

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case where the fuzzy returns a category-level `encontrados_posibles` group with `kind: "category"` (i.e. the user input matches a category token like `"postre"` against a `commerce_dynamic_database` catalog)
- **THEN** the catalog scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`
- **AND** `_fuzzy_decision(fuzzy_result)` returns `"ambiguous"` (because the category-level group is present)
- **AND** the guard does NOT fire (the scope check fails — the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`)
- **AND** the hybrid decision follows the existing scoring rule
- **AND** the case is classified by the existing scoring rule (the pre-Subphase-4.11.5 behavior is preserved for the scope check)

#### Scenario: guard does not modify _hybrid_prediction scoring formula (behavioral assertion)

- **WHEN** the test records the runner's observations before and after the guard is applied for the 11 preserved `in_memory` cases and the 36 `commerce_dynamic_database` cases
- **THEN** the recorded observations are byte-identical modulo the documented new `mismatch_category` and `mismatch_category_counts` fields for the 11 preserved `in_memory` cases
- **AND** the recorded observations are byte-identical modulo the documented new `mismatch_category` and `mismatch_category_counts` fields for the 36 `commerce_dynamic_database` cases (the guard does NOT fire for any of them because the scope is NOT `pending_product_selection_restricted`)
- **AND** the `_hybrid_prediction` scoring formula `policy.fuzzy_weight * fuzzy.get(value, 0.0) + policy.vector_weight * vector.get(value, 0.0)` is preserved verbatim (verified by the byte-identical observations of the 47 cases modulo the documented new fields; this replaces any source-string assertion)
- **AND** the guard body is a single positional tag in `_decision` that returns the string `"ambiguous"` immediately when the scope is `pending_product_selection_restricted` AND the fuzzy decision is `"ambiguous"`, with no other side effects (verified by the byte-identical observations of the 47 cases modulo the documented new fields)

#### Scenario: guard does not modify the policy grid (behavioral assertion)

- **WHEN** the test iterates `generate_policy_grid()` from `backend/services/product_recognition_calibration_policy.py` and compares the produced policies to the documented Cartesian grid
- **THEN** the weights match `(0.4, 0.6)`, `(0.5, 0.5)`, `(0.6, 0.4)`; the `unique_threshold` values match `0.65`, `0.70`, `0.75`; the `ambiguous_threshold` values match `0.35`, `0.40`, `0.45`; the `minimum_score_gap` values match `0.00`, `0.05`, `0.10`; and the `vector_top_k` values match `3`, `5`, `7`
- **AND** the total count of policies in the grid is unchanged from Subphase 4.11.4
- **AND** the Subphase 4.11 calibration policy invariants are preserved verbatim (this replaces any source-string assertion)

#### Scenario: JSON report schema is unchanged

- **WHEN** the runner produces a JSON report after the fix
- **THEN** the report carries the documented fields: `dataset_version`, `dataset_fingerprint`, `case_count`, `policy_count`, `selected_policy`, `fuzzy_metrics`, `hybrid_metrics`, `vector_metrics`, `mismatch_category_counts`, `case_results`, `policies`, `comparison`, `infrastructure_failures`, `failed_case_ids`, `latency_p50`, `latency_p95`, `eligibility`, `commerce_catalog_cache_size`
- **AND** the per-case `mismatch_category` field continues to be one of the ten documented categories or `correct`
- **AND** the `false_positives` metric in `hybrid_metrics` and `fuzzy_metrics` is the documented count of predicted-unique decisions when unique was not expected or the top-1 is not in `allowed_candidate_ids`
- **AND** no new required field is added to the report schema
- **AND** the `evidence` field in the per-case diagnostic record is preserved verbatim (the guard does not write evidence)

#### Scenario: 11 preserved in_memory cases produce byte-identical observations modulo the documented new fields

- **WHEN** the runner evaluates the 11 Subphase 4.11 cases that use an in-memory catalog fixture (catalog source: `in_memory`)
- **THEN** the guard fires for the `ambiguous-empanada-carne` case (it is an `in_memory` case whose `catalog_scope == "pending_product_selection_restricted"` AND whose `fuzzy_decision == "ambiguous"` — both guard conditions are satisfied; the case is `in_memory` in catalog source, but case origin is irrelevant to the guard)
- **AND** the guard does not fire for the 10 other `in_memory` cases: each one of them fails at least one of the two guard conditions (either `catalog_scope != "pending_product_selection_restricted"` OR `fuzzy_decision != "ambiguous"`); the other 10 `in_memory` cases are either `unique` or `unknown` and the guard's fuzzy-decision check fails on them
- **AND** the observations for the 10 other `in_memory` cases are byte-identical to the Subphase 4.11.4 observations modulo the documented new `mismatch_category` and `mismatch_category_counts` fields
- **AND** the eligibility gate is unchanged for the 10 cases that were `correct` in Subphase 4.11.4

#### Scenario: 39 currently correct cases do not regress

- **WHEN** the runner evaluates the 47-case dataset and the 39 currently correct cases (correct classification in Subphase 4.11.4)
- **THEN** every case that was `correct` in Subphase 4.11.4 is `correct` in Subphase 4.11.5
- **AND** the 19 `commerce_dynamic_database` cases whose fuzzy returns `ambiguous` continue to be classified by the existing scoring rule (the guard does not fire because the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`) — the pre-Subphase-4.11.5 behavior is preserved for these cases even though the combined hybrid ranking may contain multiple candidates
- **AND** the 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` (no false promotion)
- **AND** the 3 residual fuzzy failures (`c1-ambiguous-postre`, `c1-fuzzy-vector-disagreement-muzarrella`, `c1-ambiguous-pizza-again`) are classified as `correct` (the residual `real_fuzzy_recognizer_failure` count drops from `3` to `0`)
- **AND** the false-positive case (`ambiguous-empanada-carne`) is classified as `correct` (the residual `real_hybrid_recognizer_failure` count drops from `5` to `4`)
- **AND** the `mismatch_category_counts` aggregate agrees with the per-case `mismatch_category` field

#### Scenario: false_positive_tolerance_failed is eliminated

- **WHEN** the runner produces the post-fix JSON report and the eligibility verdict
- **THEN** `false_positives.count == 0` (the runner's `false_positives` metric is computed against the recorded predictions and no case produces a false positive)
- **AND** `hybrid_metrics.false_positives.rate == 0.0` (and the same for `fuzzy_metrics.false_positives.rate`)
- **AND** the eligibility verdict's `reasons` list does NOT contain `false_positive_tolerance_failed` (the documented Subphase 4.11.3 reason string is preserved as part of the verifier)
- **AND** the other eligibility gates (`primary_metric_improvement`, `restricted_candidate_non_regression`, `canonical_match_accuracy`, `alias_match_accuracy`, `commerce_isolation`, `latency_budget`) are documented as either passing or unchanged from Subphase 4.11.4
- **AND** the final eligibility verdict is either `eligible` (if every gate passes) or `not_eligible` with `reasons` excluding `false_positive_tolerance_failed`

### Requirement: runner classifies category-level fuzzy results as ambiguous via the typed-discriminated-union discriminator

The runner SHALL add a helper `_fuzzy_decision(result)` that inspects the recognizer result and returns `"ambiguous"` whenever an `encontrados_posibles` group carries `kind: "category"`; otherwise it falls back to the existing id-based logic (`"unique"` if `len(fuzzy_ids) == 1`, `"ambiguous"` if `len(fuzzy_ids) > 1`, `"unknown"` if `len(fuzzy_ids) == 0`). The helper is the single source of truth for the fuzzy decision used by `_prediction`, `_hybrid_prediction`, and the `_decision` hybrid guard. The helper does NOT consult the combined hybrid `ranking` to infer fuzzy ambiguity. The helper is a pure function of the recognizer result; it does not mutate the recognizer result, the visible candidates, the pending context, the handlers, the responses, or any persistence.

The runner's `_fuzzy_ids(result)` extraction walks `encontrados[].producto_presentacion_id` and `encontrados_posibles[].productos[].producto_presentacion_id` via `group.get("productos", []) or []` so it safely extracts 0 ids for category-level groups (the typed-discriminated-union discriminator `kind: "category"` is the branch point). The explicit discriminator check inside `_fuzzy_ids` ensures the category signal is captured by `_fuzzy_decision(result)` rather than silently dropped. The runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group.

#### Scenario: `_fuzzy_decision` returns `"ambiguous"` for category-level groups

- **WHEN** the test imports `_fuzzy_decision` from the runner and calls it with `{"encontrados": [], "encontrados_posibles": [{"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"}], "encontrados_no_disponibles": [], "no_encontrados": []}`
- **THEN** the helper returns `"ambiguous"`
- **AND** the helper does NOT mutate the recognizer result
- **AND** the helper does NOT consult the combined hybrid `ranking` (it is a pure function of the recognizer result)

#### Scenario: `_fuzzy_decision` falls back to id-based logic for product-level groups

- **WHEN** the test calls `_fuzzy_decision({"encontrados": [{"producto_presentacion_id": 1}], "encontrados_posibles": [], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"unique"`
- **WHEN** the test calls `_fuzzy_decision({"encontrados": [{"producto_presentacion_id": 1}], "encontrados_posibles": [{"productos": [{"producto_presentacion_id": 2}]}], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"ambiguous"`
- **WHEN** the test calls `_fuzzy_decision({"encontrados": [], "encontrados_posibles": [], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"unknown"`

#### Scenario: `_decision` returns `"ambiguous"` when the combined ranking is empty AND the fuzzy decision is `"ambiguous"` (category-level)

- **WHEN** the test imports `_decision` from the runner and calls it with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="ambiguous"`
- **THEN** `_decision` returns `"ambiguous"` (NOT `"unknown"`)
- **WHEN** the test calls `_decision` with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="unique"`
- **THEN** `_decision` returns `"unknown"`
- **WHEN** the test calls `_decision` with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="unknown"`
- **THEN** `_decision` returns `"unknown"`
- **AND** the existing scoring branches for non-empty rankings are unchanged

#### Scenario: `_flag_fuzzy_boundary_violation` ignores category-level groups

- **WHEN** the test calls `_flag_fuzzy_boundary_violation(case, fuzzy_ids)` where `fuzzy_ids` is the empty tuple (extracted from a category-level `encontrados_posibles` group with `kind: "category"` and no `productos` list)
- **THEN** the function returns `False`
- **AND** the runner's per-case `candidate_boundary_violation` failure category is NOT set for the case `c1-ambiguous-pizza-again` (input `"otra pizza"`, `allowed_candidate_ids: [1, 2, 3, 4]`) because no product ids are extracted from the category-level group

### Requirement: hybrid preserves fuzzy_unique when the vector contributes no candidates

The hybrid decision produced by the runner (`backend/services/product_recognition_calibration_runner.py`) SHALL return `"unique"` when `observation.fuzzy_decision == "unique"` AND `len(observation.vector_ids) == 0`. The guard is a single positional `if` block at the top of `_hybrid_prediction` (placed ABOVE the Subphase 4.11.5 `pending_product_selection_restricted` + `fuzzy_ambiguous` guard, which remains unchanged) that short-circuits BEFORE the existing scoring rule. When the guard fires, the runner returns a `StrategyPrediction` constructed from the fuzzy observation directly: `decision="unique"`, `top_id=observation.fuzzy_ids[0]`, `ranking=observation.fuzzy_ids`, `scores=observation.fuzzy_scores`, `canonical` and `alias` computed by `_exact_flags(case, observation.fuzzy_ids)` (the same shape the 4.11.5 guard returns). The guard does NOT modify `_decision`, `_prediction`, `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_flag_fuzzy_boundary_violation`, `_strategy_metrics`, or `_eligibility`. The guard does NOT add a new field to `StrategyPrediction` or `CaseObservation`; it does NOT modify the policy dataclass, the policy grid generator, the JSON report schema, the diagnostic surface, or the CLI surface.

The guard fires only when both conditions are met:

- `observation.fuzzy_decision == "unique"`
- `len(observation.vector_ids) == 0` (i.e. the vector contributed no candidates — the `vector_ids` tuple is empty)

The guard is scope-independent: it does NOT inspect `catalog_scope` and may therefore fire for `pending_product_selection_restricted` cases whenever the precondition holds (which is impossible in the current dataset, but the guard itself imposes no scope restriction).

The guard does NOT fire when EITHER condition fails. In particular:

- The guard does NOT fire when `observation.fuzzy_decision == "ambiguous"` (the 4.11.5 guard still fires for that case at a `pending_product_selection_restricted` scope; elsewhere the existing scoring rule applies).
- The guard does NOT fire when `observation.fuzzy_decision == "unknown"` (the existing scoring rule applies and produces `unknown`).
- The guard does NOT fire when `len(observation.vector_ids) > 0` (the existing scoring rule applies and the vector contribution is honored, even if the vector top-1 disagrees with the fuzzy top-1).
- The two guards are mutually exclusive on `fuzzy_decision`: the 4.11.5 guard requires `"ambiguous"`; the 4.11.7 guard requires `"unique"`. There is no risk of the 4.11.7 guard short-circuiting the 4.11.5 guard for any case.
- The guard is purely additive: it can only force `unique`; it never forces `ambiguous` or `unknown`.

The guard's `canonical` / `alias` flags are computed by `_exact_flags(case, observation.fuzzy_ids)` (the existing helper at `runner.py:133-148`). For the four named failing cases, the input does not equal the canonical `producto_nombre` and does not appear in any alias list, so `canonical=False, alias=False` — but the guard does NOT use the `canonical or alias` short-circuit; it forces `"unique"` based purely on the `fuzzy_decision == "unique"` AND `len(vector_ids) == 0` precondition. The `canonical` / `alias` flags are still recorded in the returned `StrategyPrediction` so the per-case `case_results` records continue to expose them (the dataset's `match_expectation` field remains the source of truth for the per-case canonical / alias expectation).

The runner's existing scoring formula `policy.fuzzy_weight * fuzzy.get(value, 0.0) + policy.vector_weight * vector.get(value, 0.0)` is preserved verbatim (verified by the byte-identical observations of the 47 cases modulo the documented new `mismatch_category` and `mismatch_category_counts` fields for the four cases). The guard short-circuits BEFORE the scoring formula; the scoring formula is only consulted when the guard does not fire.

#### Scenario: product-plus-presentation returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `product-plus-presentation` (input `"una pizza muzza grande"`, `catalog_scope: in_memory`, `id_comercio: 2`, `allowed_candidate_ids: [2]`, in-memory catalog `pizza_mozzarella_presentations` with `pid=2`, `expected_decision: unique`, `expected_producto_presentacion_id: 2`)
- **AND** the fuzzy recognizer returns `unique(pid=2)` with `observation.fuzzy_ids = (2,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=2`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: fuzzy-misspelling-mozzarella returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `fuzzy-misspelling-mozzarella` (input `"piza mozarela"`, `catalog_scope: in_memory`, `id_comercio: 3`, `allowed_candidate_ids: [100]`, in-memory catalog `pizza_mozzarella_short` with `pid=100`, `expected_decision: unique`, `expected_producto_presentacion_id: 100`)
- **AND** the fuzzy recognizer returns `unique(pid=100)` with `observation.fuzzy_ids = (100,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=100`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: supported-mozza-alias returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `supported-mozza-alias` (input `"pizza muzza"`, `catalog_scope: in_memory`, `id_comercio: 3`, `allowed_candidate_ids: [100]`, in-memory catalog `pizza_mozzarella_short` with `pid=100`, `expected_decision: unique`, `expected_producto_presentacion_id: 100`, `match_expectation: alias`)
- **AND** the fuzzy recognizer returns `unique(pid=100)` with `observation.fuzzy_ids = (100,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=100`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: multi-word-jamon-queso-dynamic returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `multi-word-jamon-queso-dynamic` (input `"empanada de jamon y queso"`, `catalog_scope: commerce_dynamic_database`, `id_comercio: 1`, `expected_decision: unique`, `expected_producto_presentacion_id_ref: pp_empanada_jamon_queso`, `match_expectation: neither`)
- **AND** the fuzzy recognizer returns `unique(pid=33)` with `observation.fuzzy_ids = (33,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=33`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: guard does not fire when vector contributes candidates

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case where `observation.fuzzy_decision == "unique"` AND `observation.vector_ids` is non-empty
- **THEN** the guard does NOT fire (the `len(vector_ids) == 0` check fails — the vector contributed candidates)
- **AND** the hybrid decision follows the existing scoring rule (the canonical/alias promotion fires, the combined `ranking` is sorted by score, and the decision is `"unique"`)
- **AND** the case classification is preserved (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: guard does not fire when fuzzy decision is ambiguous

- **WHEN** the calibration runner evaluates a case where `observation.fuzzy_decision == "ambiguous"` AND `observation.vector_ids` is empty
- **THEN** the guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"ambiguous"`)
- **AND** the existing scoring rule applies
- **AND** the case classification is preserved (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: guard does not fire when fuzzy decision is unknown

- **WHEN** the calibration runner evaluates a case where `observation.fuzzy_decision == "unknown"` AND `observation.vector_ids` is empty (e.g. `picante-restricted-refinement` with fuzzy `unknown`)
- **THEN** the guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"unknown"`)
- **AND** the existing scoring rule applies: `not ranking` AND `fuzzy_decision == "unknown"` → `"unknown"`
- **AND** the `ambiguous-empanada-carne` case is NOT triggered by this guard because its `fuzzy_decision == "ambiguous"` — the 4.11.5 guard handles it instead

#### Scenario: 4.11.5 ambiguous-empanada-carne guard still fires

- **WHEN** the calibration runner evaluates the case `ambiguous-empanada-carne` (input `"empanada de carne"`, `catalog_scope: pending_product_selection_restricted`, `id_comercio: 4`, `allowed_candidate_ids: [11, 12]`, in-memory catalog `empanada_carne_restricted` with `pid=11` and `pid=12`, `expected_decision: ambiguous`)
- **AND** the fuzzy recognizer returns ambiguous with `observation.fuzzy_ids = (11, 12)`, `observation.fuzzy_decision = "ambiguous"`
- **AND** the vector search returns `unique(pid=11)`
- **THEN** the Subphase 4.11.7 guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"ambiguous"`)
- **AND** the Subphase 4.11.5 guard fires (the scope is `pending_product_selection_restricted` AND the fuzzy decision is `"ambiguous"`)
- **AND** the hybrid decision is `"ambiguous"` regardless of the vector's top-1 contribution
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: 4.11.5 restricted ambiguous guard remains correct after the fix

- **WHEN** the focused regression suite pins the 4.11.5 guard after the 4.11.7 fix is applied
- **THEN** `ambiguous-empanada-carne` is classified as `correct` with `actual_hybrid_decision == "ambiguous"`
- **AND** the 4.11.7 guard does NOT fire for `ambiguous-empanada-carne` (the fuzzy decision is `"ambiguous"`, not `"unique"`)

#### Scenario: false_positives remain zero after the fix

- **WHEN** the runner produces the post-fix JSON report and the eligibility verdict
- **THEN** `hybrid_metrics.false_positives.count == 0` (the 4.11.7 guard returns the fuzzy prediction verbatim, which has already been validated as `unique` by `_fuzzy_decision`; the fuzzy recognizer is the production-grade recognizer audited across the Subphase 4.11 chain; no case produces a false positive)
- **AND** `hybrid_metrics.false_positives.rate == 0.0`
- **AND** `incorrect_unique_decisions.count` does NOT increase (the 4 cases that flip from `"unknown"` to `"unique"` all have `expected_decision == "unique"` and `expected_producto_presentacion_id == fuzzy_ids[0]`, so the `_correct` check returns `True`)

#### Scenario: complete 47-case calibration remains eligible

- **WHEN** the runner evaluates the 47-case dataset after the fix
- **THEN** `decision_accuracy.count == 45` (up from 41)
- **AND** `false_unknowns.count == 2` (down from 6)
- **AND** `false_positives.count == 0`
- **AND** `incorrect_unique_decisions.count == 0`
- **AND** the eligibility verdict is `eligible`
