# production-hybrid-authoritative-promotion Specification

## Purpose
TBD - created by archiving change promote-production-hybrid-authoritative-policy. Update Purpose after archive.
## Requirements
### Requirement: Production policy storage is verified independently

The operator SHALL verify a persistent production mount and the exact policy path independently from calibration. The selected report SHALL be readable JSON, have `eligibility.status == "eligible"`, be accepted by the existing loader, and retain its recorded SHA-256 across the agreed production redeploy boundary while shadow remains active.

#### Scenario: Calibration artifact is unavailable in production

- **WHEN** production cannot read the selected artifact at a persistent verified path
- **THEN** production SHALL remain in shadow
- **AND** the calibration path SHALL NOT be assumed or configured

### Requirement: Production activation is staged and reversible

The policy path SHALL be configured and loaded while production remains in shadow. Only then may authoritative mode be configured, with a controlled deploy and immediate rollback to shadow available. The operation SHALL not use Twilio, real-message traffic or production-data probes.

#### Scenario: Production activation is unhealthy

- **WHEN** the deploy, loader, factory or controlled health gate is unhealthy
- **THEN** the operator SHALL return production to shadow
- **AND** evidence artifacts SHALL be preserved

### Requirement: No eligible calibration report alone enables production

An eligible report from calibration SHALL be necessary but insufficient for production activation. Production-specific persistence, dependency, configuration, controlled validation and approval gates SHALL all be satisfied.

#### Scenario: A production prerequisite is missing

- **WHEN** any required production gate is absent
- **THEN** no authoritative production activation occurs
- **AND** Fuzzy remains the business-authoritative fallback through shadow
