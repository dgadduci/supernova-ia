# Capability: phase-4-regression-closure

## Purpose

Define the minimum evidence required to close Phase 4 product recognition
without changing production behavior. The closure gate verifies fuzzy, vector,
shadow, calibration, pending ambiguity, and controlled authoritative hybrid
paths through their existing tests and executable calibration command, while
separately classifying documented pre-existing debt.

## Requirements

### Requirement: Phase 4 closure uses the documented minimum regression matrix

The Phase 4 closure review SHALL execute the existing fuzzy, vector/embedding,
shadow, calibration, pending ambiguity, settings/factory, and controlled
hybrid test groups documented in the active 4.13 design. It SHALL execute the
47-case calibration CLI with diagnostic output. The closure review SHALL NOT
add new behavior, alter tests or fixtures, change the dataset or policy grid,
or substitute a new harness for these existing boundaries.

#### Scenario: Required matrix passes

- **WHEN** every required 4.13 command exits zero
- **AND** the calibration output reports `eligibility.status == "eligible"`
- **THEN** the regression matrix supplies sufficient functional evidence to recommend Phase 4 closure

#### Scenario: Required Phase-4 failure blocks closure

- **WHEN** a required test, focused Ruff check, compile check, calibration command, or eligible verdict fails
- **THEN** Phase 4 closure is blocked
- **AND** the failure is recorded as a new regression unless reproducible evidence identifies an unchanged excluded baseline
- **AND** no corrective implementation is performed as part of closure verification

### Requirement: Closure preserves product-recognition safety boundaries

The closure matrix SHALL prove the existing invariants: fuzzy remains the safe
fallback; shadow mode remains non-authoritative; hybrid activation remains
configuration-driven and reversible; a hybrid embedding/vector technical
failure returns the fuzzy result; vector results are constrained to the
caller-provided catalog; commerce isolation is preserved; and pending
candidate sets are not widened. Recognizers SHALL continue not to commit or
roll back caller-owned transactions.

#### Scenario: Hybrid failure uses fuzzy fallback

- **WHEN** the controlled-hybrid regression suite simulates an embedding or vector technical failure
- **THEN** the recognizer returns the fuzzy result under the existing contract
- **AND** the failure remains observable through the existing metrics boundary

#### Scenario: Restricted pending candidates cannot reappear

- **WHEN** the pending and controlled-hybrid suites use a narrowed candidate catalog
- **THEN** no vector or resolution outcome contains an ID outside that catalog

### Requirement: Documented debt is verified rather than assumed

The closure review SHALL run the separate smoke, Ruff, and mypy diagnostic
commands documented in the 4.13 design and SHALL classify each result by its
exact identifier and output. The strict-mypy baseline is specifically
evidenced by
`openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/tasks.md:35`,
which records 16 pre-existing generic-type errors in
`backend/recognizers/product_recognizer.py`. The archived four smoke-test
failures, the three `test_llm_settings.py` B017 findings, that generic-type
mypy inventory, and the two explicitly marked raw-fuzzy baseline limitations
MAY be deferred when they are unchanged, reduced, line-number shifted, or
diagnostically equivalent, provided they do not change runtime/business
behavior or overlap a required Phase-4 boundary.

#### Scenario: Non-material debt variation is deferred

- **WHEN** an optional diagnostic reproduces a documented baseline issue with
  the same or fewer findings, line-number drift, or equivalent diagnostic
  wording
- **AND** all required Phase-4 commands pass
- **THEN** the issue is recorded as `verified_pre_existing` or
  `non_blocking_variation`
- **AND** it does not block the Phase-4 closure recommendation

#### Scenario: Material debt variation is a regression candidate

- **WHEN** an optional diagnostic introduces a materially new issue, increases
  the documented debt, changes runtime/business behavior, or affects the
  required Phase-4 matrix
- **THEN** it is recorded as `new_regression`
- **AND** it blocks the Phase-4 closure recommendation pending separate approval

### Requirement: Closure remains reversible and user-controlled

The 4.13 change SHALL modify only its OpenSpec proposal artifacts until the
user explicitly authorizes implementation or Phase-4 closure. It SHALL NOT
perform a migration, sync specifications, archive an OpenSpec change, or
close Phase 4 itself.

#### Scenario: Verification concludes without state transition

- **WHEN** the 4.13 verification report is complete
- **THEN** Phase 4 remains awaiting explicit user approval
- **AND** no OpenSpec sync or archive operation has run

#### Scenario: Environment blocker requires later supported execution

- **WHEN** the current environment cannot execute a required command
- **THEN** the result is recorded as `environment_blocker`, not as a regression
- **AND** Phase 4 closure is not recommended until that command succeeds in the supported local environment