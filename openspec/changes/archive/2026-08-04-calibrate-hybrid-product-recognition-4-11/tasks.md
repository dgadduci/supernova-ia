## 1. Calibration dataset

- [x] 1.1 Version the approved calibration dataset from `backend/tests/fixtures/product_recognizer_baseline.json`, preserving all eleven Subphase 4.1 cases, IDs, inputs, catalog semantics, and expected outcomes; add `id_comercio`, expected decision/product ID, allowed/restricted candidate IDs, canonical/alias expectation, presentation-resolution expectation, and metric category.
- [x] 1.2 Add deterministic catalog/database seed references so every baseline case, including `multi-word-jamon-queso-dynamic`, executes during calibration instead of being skipped.
- [x] 1.3 Audit category coverage and add only the smallest representative fixture cases missing for commerce isolation and restricted-candidate exclusion.
- [x] 1.4 Implement strict dataset validation for schema version, unique case IDs, decision enums, expected-ID applicability, stable/non-overlapping candidate lists, deterministic seed references, categories, and absence of production customer data.
- [x] 1.5 Compute the dataset SHA-256 fingerprint from canonical sorted-key UTF-8 JSON; do not hard-code or label a fingerprint as calibrated.

## 2. Typed policy and parameter grid

- [x] 2.1 Add frozen `HybridDecisionPolicy` with `fuzzy_weight`, `vector_weight`, `unique_threshold`, `ambiguous_threshold`, `minimum_score_gap`, and `vector_top_k`.
- [x] 2.2 Validate finite weights in `[0, 1]`, weight sum equal to `1`, thresholds/gap in `[0, 1]`, `unique_threshold >= ambiguous_threshold`, and `vector_top_k > 0`.
- [x] 2.3 Implement the deterministic grid of weight pairs `(0.4, 0.6)`, `(0.5, 0.5)`, `(0.6, 0.4)`; unique thresholds `0.65/0.70/0.75`; ambiguous thresholds `0.35/0.40/0.45`; score gaps `0.00/0.05/0.10`; and top-k `3/5/7`, labeling all values as provisional search points.
- [x] 2.4 Remove invalid/duplicate policies deterministically and preserve declared grid order without external ML or optimization libraries.
- [x] 2.5 Implement tie-breaking by fewer false positives, fewer incorrect unique decisions, higher top-1 accuracy, fewer false unknowns, lower top-k, closest normalized Manhattan distance to provisional defaults, then declared order.

## 3. Offline case observation and policy evaluation

- [x] 3.1 Implement a calibration runner that selects cases deterministically after commerce/limit filters and executes fuzzy exactly once per case.
- [x] 3.2 Generate one query embedding and execute one commerce-scoped vector search per case at the maximum grid top-k, then derive each policy's top-k slice without repeated infrastructure calls.
- [x] 3.3 Pass allowed candidate IDs to vector search, preserve restricted IDs, verify fuzzy/vector/hybrid outputs contain only permitted commerce/candidate IDs, and classify boundary violations.
- [x] 3.4 Calculate observational hybrid rankings and exact canonical/alias then unique/ambiguous/unknown decisions from supplied policies without invoking or modifying the runtime recognizer.
- [x] 3.5 Compare fuzzy, vector-only, and each hybrid policy with expected decision, product-presentation, match type, presentation resolution, and restrictions.
- [x] 3.6 Continue after individual fuzzy, embedding, or vector failures; keep fuzzy evaluable when vector infrastructure fails; record sanitized failure categories/IDs; treat zero evaluable hybrid cases as total failure.

## 4. Metrics and selection

- [x] 4.1 Implement aggregate counts/rates for total cases, decision accuracy, top-1 accuracy, recall at top-k, false positives, false unknowns, incorrect unique decisions, and correct/incorrect ambiguities using the specification's denominators.
- [x] 4.2 Implement presentation-resolution, canonical-match, alias-match, restricted-candidate, fuzzy baseline, vector-only, hybrid, and fuzzy/vector top-1 agreement metrics with zero denominators serialized as `null`.
- [x] 4.3 Keep infrastructure-failed cases in applicable denominators, collect infrastructure-failure count and failed case IDs in stable dataset order, and prevent failures from counting as correct.
- [x] 4.4 Compute p50/p95 with the specified nearest-rank algorithm over attempted case durations and retain only safe scalar timing data.
- [x] 4.5 Produce per-category metrics by intersecting every metric population with the category population.
- [x] 4.6 Select the best policy using the explicit primary metric and deterministic tie-break sequence; report selection separately from runtime eligibility.

## 5. Baseline comparison and 4.12 eligibility

- [x] 5.1 Generate comparison rows containing `metric`, `fuzzy_baseline`, `selected_hybrid_policy`, and `absolute_difference` over identical populations.
- [x] 5.2 Accept explicit eligibility inputs for primary metric, required improvement, false-positive tolerance, and latency budget; do not invent missing values.
- [x] 5.3 Gate eligibility on primary improvement, false-positive tolerance, restricted-candidate non-regression, exact canonical/alias preservation, commerce isolation, and latency budget.
- [x] 5.4 Emit `pending` plus stable missing-input reasons when criteria are incomplete, `not_eligible` plus failed-gate reasons when any gate fails, and `eligible` only when every input and gate passes.

## 6. Safe JSON report

- [x] 6.1 Define a machine-readable report containing dataset version/fingerprint, embedding model/dimension, case/policy counts, selected policy, fuzzy/vector/hybrid and per-category metrics, differences, failures, failed IDs, latency p50/p95, eligibility, and reasons.
- [x] 6.2 Serialize with sorted keys, stable list order, finite JSON numbers, and byte-identical output for equal recorded observations.
- [x] 6.3 Exclude input text, vectors, credentials, prompts, source documents, production customer data, stack traces, raw exceptions, sessions, and connections from report contracts and output.
- [x] 6.4 Write reports atomically so failures do not leave a partial output file.

## 7. Local CLI

- [x] 7.1 Add `python -m backend.cli.calibrate_product_recognizer` with `--dataset`, `--output`, `--commerce-id`, and `--limit`.
- [x] 7.2 Validate dataset/options/configuration before calibration, create one database session through the project session factory, commit nothing, and close the owned session exactly once in `finally`.
- [x] 7.3 Write the JSON report, print a concise case/policy/selected-policy/eligibility summary, and avoid sensitive or raw failure output.
- [x] 7.4 Return non-zero for invalid dataset, configuration, database failure, or total calibration failure; allow a reportable partial run when individual embedding/vector failures leave at least one evaluable hybrid case.
- [x] 7.5 Verify the CLI neither modifies nor uses `PRODUCT_RECOGNIZER_MODE` to determine calibration behavior.

## 8. Focused tests

- [x] 8.1 Test every policy validation invariant, frozen behavior, deterministic grid generation, duplicate elimination, and deterministic tie-breaking.
- [x] 8.2 Test preserved exact canonical and alias behavior plus expected unique, ambiguous, and unknown decisions.
- [x] 8.3 Test restricted candidates, allowed-candidate enforcement, cross-commerce isolation, and deterministic execution of the formerly skipped dynamic baseline case.
- [x] 8.4 Test embedding and vector failures, continuation to later cases, sanitized failure output, total-failure detection, and fuzzy execution exactly once per case across multiple policies.
- [x] 8.5 Test every metric denominator, infrastructure failures remaining in denominators, zero-denominator `null`, per-category populations, and nearest-rank p50/p95.
- [x] 8.6 Test JSON determinism/safety, dataset fingerprint derivation, forbidden-field absence, finite values, and atomic output.
- [x] 8.7 Test fuzzy baseline comparison rows and explicit `pending`/`not_eligible`/`eligible` Subphase 4.12 outcomes for every gate.
- [x] 8.8 Test CLI options, owned-session closure on success/failure, no commit, concise output, exit codes, and no `PRODUCT_RECOGNIZER_MODE` mutation.
- [x] 8.9 Run focused regressions for Subphases 4.5–4.10.1 and confirm fuzzy remains authoritative and runtime shadow/contracts/defaults are unchanged.

## 9. Implementation verification

- [x] 9.1 During implementation, run the repository-provided formatter, linter, and strict typecheck commands over only the added/touched calibration files and resolve failures.
- [x] 9.2 During implementation, run the focused calibration and Subphase 4.5–4.10.1 regression tests and report results.
- [x] 9.3 Confirm no handlers, resolvers, pending contexts, intents, orders, responses, persistence contracts, canonical specs, runtime modes, provisional defaults, or calibrated runtime defaults changed.
- [x] 9.4 Run `openspec validate calibrate-hybrid-product-recognition-4-11 --strict` and report the revised scope, proposed files, dataset strategy, metrics, parameter grid, validation result, and real-code mismatches.
