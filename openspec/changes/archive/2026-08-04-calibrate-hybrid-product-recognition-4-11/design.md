## Context

Subphase 4.1 established `backend/tests/fixtures/product_recognizer_baseline.json` with eleven cases and seven catalog fixtures. The static baseline harness executes fuzzy directly, while its dynamic commerce case is skipped by that harness and depends on database seeding. Subphases 4.5–4.9 added embeddings and commerce-scoped vector search. Subphases 4.10–4.10.1 added a shadow service that computes an observational hybrid ranking and safely records vector failures while returning the fuzzy result unchanged.

Current runtime values are provisional: fuzzy/vector weights `0.5/0.5`, unique threshold `0.7`, ambiguous threshold `0.4`, minimum score gap `0.05`, and vector top-k `5`. They define the center of the search grid only. They are not calibrated, and this change does not replace, rename, or promote them.

## Goals / Non-Goals

**Goals:**

1. Build a deterministic, approved calibration dataset rooted in the complete Subphase 4.1 baseline.
2. Define and validate a frozen typed decision policy.
3. Evaluate fuzzy, vector-only, and observational hybrid behavior offline without changing runtime authority.
4. Search a small deterministic parameter grid and select a policy with deterministic tie-breaking.
5. Generate safe machine-readable evidence with explicit metric denominators and Subphase 4.12 eligibility.
6. Provide a local CLI that owns database resources and can be run repeatedly against the same approved dataset.

**Non-Goals:**

- Adding a `hybrid` runtime mode or making hybrid authoritative.
- Changing the shadow service, comparison/observation dataclasses, recorder, factory, runtime settings, provisional defaults, or `PRODUCT_RECOGNIZER_MODE`.
- Automatically installing a selected policy as a runtime default.
- Changing handlers, resolvers, pending contexts, intents, orders, responses, or persistence contracts.
- Editing canonical specs, synchronizing specs, archiving the change, online learning, or introducing external ML/optimization libraries.
- Using production customer text or production calibration data.

## Decisions

### Decision: Version the baseline as the calibration dataset foundation

The approved calibration dataset will preserve every Subphase 4.1 `case_id`, input, catalog semantics, and expected fuzzy outcome. Its schema will add, per case:

- `case_id`
- `id_comercio`
- `input_text`
- `expected_decision`: `unique`, `ambiguous`, or `unknown`
- `expected_producto_presentacion_id`: nullable when not applicable
- `allowed_candidate_ids`
- `restricted_candidate_ids`: empty when not applicable
- `match_expectation`: `canonical`, `alias`, or `neither`
- `presentation_resolution_expectation`: `resolved`, `ambiguous`, `unknown`, or `not_applicable`
- `category`

Catalog data and deterministic seed references remain part of the dataset package. The version is explicit. Its fingerprint is SHA-256 over canonical UTF-8 JSON with sorted object keys and stable array ordering; no claimed fingerprint is committed before the runner computes it.

A coverage audit may add the smallest representative set needed for behavior absent from the eleven baseline cases, particularly cross-commerce isolation and explicit restricted-candidate exclusion. Existing cases are never rewritten merely to improve metrics. The database-dependent baseline case must be seeded and executed by calibration rather than silently skipped.

**Alternatives considered:** replacing the baseline was rejected because it would lose the frozen regression contract; calibrating from production logs was rejected because it is not deterministic or approved and may contain customer data.

### Decision: Use one frozen policy contract

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

Construction validates finite numeric values, both weights in `[0, 1]`, the weight sum equal to `1` within the project-standard floating-point tolerance, thresholds and score gap in `[0, 1]`, `unique_threshold >= ambiguous_threshold`, and `vector_top_k > 0`. Invalid policies fail before database or embedding work begins.

### Decision: Separate case observation from policy evaluation

For each selected case, the runner:

1. executes fuzzy exactly once;
2. creates the query embedding exactly once;
3. executes vector search once for the case's `id_comercio` at the maximum top-k needed by the grid;
4. passes the allowed/restricted candidate boundary to search and verifies returned IDs remain within it;
5. stores safe scalar scores/IDs and timings as an in-memory observation;
6. derives each policy's top-k slice, observational hybrid ranking, and decision from that observation;
7. compares fuzzy, vector-only, and each hybrid policy with the expected outcome;
8. accumulates metrics; and
9. records a sanitized failure category and continues after individual embedding/vector failures.

Fuzzy failures invalidate the case for all strategies but do not abort remaining cases. An embedding or vector failure leaves the fuzzy baseline evaluable, marks vector/hybrid infrastructure failure for that case, and never converts missing infrastructure into a successful unknown prediction. A total calibration failure means no policy has any evaluable hybrid case.

Restricted cases send only `allowed_candidate_ids` to vector search and assert that all `restricted_candidate_ids` are absent from fuzzy/vector/hybrid candidates. Commerce-scoped search always uses the case's `id_comercio`, regardless of the optional CLI filter.

**Alternatives considered:** invoking vector search per policy was rejected because it multiplies infrastructure work and latency noise; routing through runtime shadow mode was rejected because calibration must not modify or depend on runtime authority.

### Decision: Use a bounded deterministic default grid

The default search grid is:

- fuzzy/vector weights: `(0.4, 0.6)`, `(0.5, 0.5)`, `(0.6, 0.4)`
- unique threshold: `0.65`, `0.70`, `0.75`
- ambiguous threshold: `0.35`, `0.40`, `0.45`
- minimum score gap: `0.00`, `0.05`, `0.10`
- vector top-k: `3`, `5`, `7`

These are deterministic candidate points around the current provisional center, not calibrated defaults. The Cartesian product is generated in declared order, invalid combinations are rejected by policy validation, duplicate policies are removed while preserving first occurrence, and the number evaluated is reported.

The agreed primary metric is an explicit dataset/runner eligibility input. Policies maximize that metric. Equal values are resolved in this order:

1. fewer false positives;
2. fewer incorrect `unique` decisions;
3. higher top-1 accuracy;
4. fewer false unknowns;
5. lower `vector_top_k`;
6. minimum normalized Manhattan distance from `(0.5, 0.5, 0.7, 0.4, 0.05, 5)`;
7. declared grid order as the final deterministic stabilizer.

No Bayesian optimization, genetic algorithm, online learning, or external ML library is used.

### Decision: Define metric populations before execution

Let `N` be all valid cases selected after `--commerce-id` and `--limit`; infrastructure-failed cases remain in applicable denominators so failures cannot improve accuracy. Let `N_id` be cases with an expected product-presentation ID, `N_presentation` cases whose presentation expectation is not `not_applicable`, `N_canonical` canonical cases, `N_alias` alias cases, `N_restricted` cases with candidate restrictions, and `N_category(c)` cases in category `c`. A rate with denominator zero is JSON `null`, never zero.

- `total_cases`: `N`.
- `decision_accuracy`: cases whose predicted decision equals expected decision / `N`.
- `top_1_accuracy`: cases whose top-ranked ID equals expected ID / `N_id`.
- `recall_at_top_k`: cases whose expected ID appears in the strategy ranking up to that strategy's top-k / `N_id`.
- `false_positives`: count of cases predicted `unique` when expected is not `unique`, plus expected-unique cases whose predicted unique ID is not allowed; companion rate denominator is `N`.
- `false_unknowns`: count of cases predicted `unknown` when expected is not `unknown`; companion rate denominator is cases expected not-unknown.
- `incorrect_unique_decisions`: count of predicted `unique` cases whose expected decision is not `unique` or whose top ID differs from the expected ID; companion rate denominator is predicted-unique cases.
- `correct_ambiguities`: count of expected-ambiguous cases predicted ambiguous; companion rate denominator is expected-ambiguous cases.
- `incorrect_ambiguities`: count of predicted-ambiguous cases whose expected decision is not ambiguous; companion rate denominator is predicted-ambiguous cases.
- `presentation_resolution_accuracy`: cases matching both presentation-resolution expectation and expected ID when one exists / `N_presentation`.
- `canonical_match_accuracy`: canonical cases preserving expected unique ID and canonical classification / `N_canonical`.
- `alias_match_accuracy`: alias cases preserving expected unique ID and alias classification / `N_alias`.
- `restricted_candidate_accuracy`: restricted cases whose fuzzy/vector/hybrid candidate outputs are subsets of allowed IDs, exclude restricted IDs, and match the expected decision/ID / `N_restricted`.
- `fuzzy_baseline_accuracy`: fuzzy decision-correct cases / `N`.
- `vector_only_accuracy`: vector-only decision-correct cases under the evaluated policy's thresholds/gap/top-k / `N`.
- `hybrid_accuracy`: hybrid decision-correct cases / `N`.
- `fuzzy_vector_top_1_agreement`: cases with equal non-null fuzzy and vector top-1 IDs / cases where both strategies produced a top-1 ID.
- `latency_p50` and `latency_p95`: nearest-rank percentiles over measured end-to-end case durations for all attempted cases; sorted ascending, rank `ceil(p * count)`, one-based and clamped to the available range. Component timings may be reported additionally.
- `infrastructure_failures`: count of cases with fuzzy, embedding, vector, or database failure / `N`.
- `failed_case_ids`: stable dataset-order IDs for those failures.

Per-category metrics apply the same definitions after replacing each population with its intersection with category `c`. Fuzzy, selected hybrid, and absolute differences use the same populations.

### Decision: Eligibility is explicit and conservative

The report receives or reads approved eligibility inputs: primary metric name, required primary improvement, false-positive tolerance, and latency budget. Restricted-candidate non-regression, exact canonical/alias preservation, and commerce isolation are mandatory zero-regression gates. If any configurable input is absent, the report sets eligibility to `pending` and names the missing input. Otherwise eligibility is `eligible` only when every gate passes; it is `not_eligible` with stable reason codes when any gate fails. The runner never invents tolerances.

### Decision: Serialize a safe deterministic JSON report

The report contains dataset version/fingerprint, embedding model/dimension, selected case count, policy count, selected policy, fuzzy/vector/hybrid metrics, comparison rows, per-category metrics, infrastructure failures, failed IDs, latency p50/p95, eligibility status, and reasons. Serialization uses sorted keys, stable list ordering, finite JSON numbers, and no environment-dependent object representations. The dataset fingerprint and metric content are deterministic for fixed observations; measured latency remains explicitly observational.

The report excludes input text, vectors, credentials, prompts, source documents, stack traces, raw exception text, and production customer data.

### Decision: CLI owns infrastructure lifecycle

`python -m backend.cli.calibrate_product_recognizer` accepts `--dataset`, `--output`, `--commerce-id`, and `--limit`. It validates arguments and dataset before calibration, creates one database session using the project's session factory, passes dependencies to the runner, commits nothing, and closes the session in `finally`. It writes the JSON report atomically, prints only a concise count/policy/eligibility summary, and returns non-zero for invalid dataset, invalid configuration, database failure, or total calibration failure. Individual embedding/vector failures remain reportable partial results and do not alone force a non-zero exit. The CLI neither reads nor writes `PRODUCT_RECOGNIZER_MODE`.

## Risks / Trade-offs

- [The original dynamic baseline case is currently skipped by the static baseline harness] → Seed its deterministic commerce/catalog data in the calibration fixture and fail dataset validation if its reference cannot resolve.
- [Small datasets can overfit a grid] → Preserve all baseline cases, add only representative gaps, report per-category results, and require later human approval before 4.12.
- [Infrastructure failures can distort scores] → Keep failed cases in applicable denominators, report stable failure categories/IDs, and disallow selection when no hybrid cases are evaluable.
- [Latency varies between runs] → Use a specified percentile algorithm, report sample count and environment/model metadata, and treat the latency budget as an explicit input.
- [Candidate leakage across commerce or pending restrictions] → Supply both boundaries to search, verify every returned ID, and make isolation/restriction failures eligibility blockers.
- [Existing production call sites bypass the recognizer factory] → Record this as a pre-existing runtime mismatch; do not change those handlers/resolvers in 4.11 because the runner invokes collaborators offline and no runtime rollout is allowed.

## Migration Plan

1. Implement dataset validation/enrichment while retaining all Subphase 4.1 cases.
2. Implement policy, observation, grid, metrics, eligibility, report, and CLI modules without runtime wiring.
3. Add focused and regression tests.
4. Run calibration locally only when an approved dataset and seeded database are available.
5. Review the JSON report manually. Any runtime promotion belongs to a later explicitly approved change.

Rollback removes only offline calibration modules/fixtures/tests; runtime behavior is unchanged throughout. This change does not synchronize or archive specs.

## Open Questions

- Which metric is the agreed primary metric for 4.12 eligibility?
- What required primary improvement, false-positive tolerance, and latency budget are approved?
- Which embedding model/environment is approved for the reproducible calibration run?

Until these inputs are supplied, eligibility must remain `pending` even if a policy is selected.
