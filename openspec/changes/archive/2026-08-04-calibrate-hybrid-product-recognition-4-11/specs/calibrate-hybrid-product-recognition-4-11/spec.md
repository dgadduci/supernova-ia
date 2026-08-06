## ADDED Requirements

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
