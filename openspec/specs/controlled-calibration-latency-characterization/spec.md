# controlled-calibration-latency-characterization Specification

## Purpose
TBD - created by archiving change characterize-controlled-calibration-latency. Update Purpose after archive.
## Requirements
### Requirement: Calibration report includes safe aggregate stage timings

The calibration report SHALL include an additive latency-breakdown block for fuzzy, embedding, vector-search and evaluation stages. Each populated stage SHALL expose only aggregate counts and finite timing statistics; it SHALL NOT contain case text, case identifiers, vectors, prompts, candidate results, credentials, URLs, SQL, stack traces or raw exception messages.

#### Scenario: A completed controlled run is inspectable without case evidence

- **WHEN** the controlled calibration CLI completes with a JSON report
- **THEN** the report contains aggregate p50, p95 and maximum timing evidence for its measured stages
- **AND** an operator can compare stages across reports without reading diagnostic records or customer-like text

### Requirement: Stage failures remain technical failures

Embedding and vector-search failures SHALL remain technical calibration failures and SHALL be counted in a stable safe category. The instrumentation SHALL NOT convert a failure into a recognized result, expand a candidate set, alter Fuzzy fallback semantics or expose the underlying exception.

#### Scenario: Embedding failure is summarized safely

- **WHEN** embedding fails for one or more calibration cases
- **THEN** the embedding stage reports an incremented safe failure count
- **AND** no raw provider error or input text is written to the report

### Requirement: Latency evidence does not alter eligibility

The latency breakdown SHALL be observational. The existing total-latency metric, frozen dataset eligibility block and `eligibility.status` SHALL remain the authority for policy candidacy. This capability SHALL NOT change the latency budget, thresholds, selected policy or recognizer mode.

#### Scenario: Repeated p95 remains over budget

- **WHEN** one or more reports show total p95 above the frozen budget
- **THEN** the report remains `not_eligible` according to the existing rule
- **AND** the added breakdown may identify a follow-up investigation target
- **BUT** it SHALL NOT raise the budget or enable authoritative hybrid
