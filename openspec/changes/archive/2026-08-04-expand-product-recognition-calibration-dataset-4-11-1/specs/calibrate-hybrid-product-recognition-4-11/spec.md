## ADDED Requirements

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
