# railway-hybrid-recognition-calibration-policy Specification

## Purpose
TBD - created by archiving change calibrate-railway-hybrid-recognition-policy. Update Purpose after archive.
## Requirements
### Requirement: Calibration uses only the frozen controlled dataset

The operator SHALL invoke the existing calibration CLI only with
`backend/data/product_recognition_calibration_cases.json` and against a
confirmed controlled Railway catalog that satisfies its dataset references and
fingerprints. The invocation SHALL remain outside message processing and SHALL
not use customer messages, customer records, orders, sessions, Twilio traffic
or production-log samples.

#### Scenario: Catalog mismatch stops the calibration gate

- **WHEN** a required dataset reference or catalog fingerprint does not match
- **THEN** the calibration is not accepted as policy evidence
- **AND** no runtime policy path or recognizer mode is changed

### Requirement: Eligibility status is the sole policy verdict

The calibration JSON report's `eligibility.status` SHALL be the authoritative
verdict for policy candidacy. A successful CLI process alone SHALL NOT imply
that the report is eligible. Only the literal `"eligible"` may proceed to
artifact-persistence verification; `"not_eligible"`, `"pending"`, missing or
malformed eligibility SHALL block promotion.

#### Scenario: Ineligible report preserves fuzzy authority

- **WHEN** the report status is not `"eligible"`
- **THEN** `PRODUCT_RECOGNIZER_MODE=shadow` remains unchanged
- **AND** fuzzy remains the sole authoritative recognizer
- **AND** the report is not installed or referenced as a runtime policy

### Requirement: Policy artifact requires verified persistent Railway storage

An eligible report SHALL become a runtime-policy candidate only after it is
stored atomically in an operator-confirmed persistent Railway mount, read back
as valid JSON, and proven to survive the agreed restart/redeploy boundary. The
mount path SHALL NOT be assumed from `/tmp`, an image-layer path, an archived
report or an undocumented location.

#### Scenario: Ephemeral output cannot enable authoritative hybrid

- **WHEN** an eligible report exists only in `/tmp` or another unverified
  ephemeral location
- **THEN** no `HYBRID_AUTHORITATIVE_POLICY_PATH` is configured
- **AND** authoritative hybrid is not enabled

### Requirement: Promotion is independently approved and reversible

This calibration change SHALL NOT enable `hybrid_authoritative`. A later
change may do so only after an eligible report, verified persistent artifact,
valid configuration and controlled validation have been reviewed and explicitly
approved. Returning to `shadow` or `fuzzy` SHALL remain the safe reversal; the
evidence report is not deleted as part of that reversal.

#### Scenario: Missing promotion prerequisite blocks activation

- **WHEN** any eligibility, persistence, configuration or controlled-validation
  prerequisite is absent
- **THEN** the system remains in `shadow` or `fuzzy`
- **AND** no real-message or Twilio test is started by this change
