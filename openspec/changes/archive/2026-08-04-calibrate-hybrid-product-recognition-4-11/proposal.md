## Why

Subphase 4.10.1 leaves hybrid product recognition strictly observational and its weights, thresholds, score gap, and vector top-k provisional. Subphase 4.11 must establish an auditable offline calibration workflow over an approved deterministic dataset before any value can be considered for Subphase 4.12.

The current proposal incorrectly treats unmeasured constants and a claimed fingerprint as calibrated runtime defaults. This revision replaces that approach with reproducible dataset evaluation, bounded parameter search, explicit metrics, and a machine-readable report while fuzzy recognition remains authoritative.

## What Changes

- Extend the Subphase 4.1 baseline into a versioned deterministic calibration dataset. Preserve all existing baseline cases and expected outcomes, enrich each case with commerce, candidate-boundary, match-type, presentation-resolution, and metric-category metadata, and add only representative cases for uncovered behavior.
- Add a frozen `HybridDecisionPolicy` dataclass with validated fuzzy/vector weights, unique and ambiguous thresholds, minimum score gap, and vector top-k.
- Add an offline runner that executes fuzzy once per case, generates one query embedding, performs commerce-scoped vector search while preserving restricted candidates, computes observational rankings, applies supplied policies, records failures without aborting the remaining cases, and never invokes or changes the runtime recognizer.
- Evaluate a bounded deterministic grid around the current provisional 4.10 values. Grid entries are search inputs, not calibrated values. Select equal-scoring policies by fewer false positives, fewer incorrect `unique` decisions, higher top-1 accuracy, fewer false `unknown` decisions, lower top-k, then shortest distance from the provisional defaults.
- Produce explicitly denominated aggregate and per-category metrics, including fuzzy baseline, vector-only, and hybrid comparisons, candidate restrictions, exact canonical/alias behavior, presentation resolution, infrastructure failures, and latency percentiles.
- Compare the selected hybrid policy with fuzzy in a deterministic table containing `metric`, `fuzzy_baseline`, `selected_hybrid_policy`, and `absolute_difference`.
- Gate Subphase 4.12 eligibility on an explicit primary metric, false-positive tolerance, restricted-candidate non-regression, exact canonical and alias preservation, commerce isolation, and latency budget. Missing tolerance, primary-metric, or budget inputs produce pending eligibility rather than invented criteria.
- Write a deterministic, safe JSON report with dataset/model provenance, policies evaluated, selected policy, metrics, differences, failures, latency, and eligibility reasons. The report excludes vectors, credentials, prompts, stack traces, and production customer data.
- Add the local CLI `python -m backend.cli.calibrate_product_recognizer` with `--dataset`, `--output`, `--commerce-id`, and `--limit`. It owns and closes its database session, writes the report, prints a concise summary, and exits non-zero for invalid input/configuration, database failure, or total calibration failure.
- Add focused tests for policy validation, deterministic search and tie-breaking, decisions and exact matches, candidate and commerce boundaries, failure continuation, one fuzzy execution per case, metric denominators and percentiles, JSON safety, baseline comparison, explicit eligibility, and Subphase 4.5–4.10.1 regressions.
- Do not promote any generated policy into runtime defaults automatically. A report is evidence for a later explicit decision, not runtime configuration.

## Capabilities

### New Capabilities

- `calibrate-hybrid-product-recognition-4-11`: deterministic offline dataset calibration, bounded policy search, metrics, safe JSON reporting, eligibility assessment, and local CLI execution.

### Modified Capabilities

- `product-recognition-shadow-mode`: clarify that Subphase 4.11 consumes its observational scoring semantics for offline evaluation only; fuzzy remains authoritative and the runtime shadow contract and provisional values remain unchanged.

## Impact

- Proposed dataset work: version the existing `backend/tests/fixtures/product_recognizer_baseline.json` contract or derive a dedicated approved calibration fixture from it without removing or changing the eleven baseline cases.
- Proposed offline modules: typed dataset/policy/report contracts, calibration runner and deterministic grid/metric helpers under backend service or calibration modules, plus `backend/cli/calibrate_product_recognizer.py`.
- Proposed tests: focused calibration dataset, policy, runner, metrics, report, CLI, and regression tests under `backend/tests/`.
- Existing collaborators are reused through their current protocols: `FuzzyProductRecognizer`, the embedding client, and `ProductPresentationVectorSearchService`.
- No external ML or optimization dependencies, schema migration, HTTP endpoint, production persistence contract, runtime recognizer mode, or automatic settings promotion.
- No changes to handlers, resolvers, pending contexts, intents, orders, customer responses, runtime recognizer contracts, canonical specs, or `PRODUCT_RECOGNIZER_MODE`.
