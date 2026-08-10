# Capability: railway-hybrid-authoritative-promotion

## Purpose

Promote a verified eligible calibration report to an authoritative-hybrid configuration only in the controlled Railway calibration environment, with a tested shadow rollback.

## ADDED Requirements

### Requirement: Promotion requires a verified persistent eligible artifact

Before configuring authoritative mode, the operator SHALL verify the selected report is readable JSON in the confirmed persistent mount, has `eligibility.status == "eligible"`, carries a loader-valid `selected_policy`, and has the same recorded SHA-256 before and after a controlled redeploy while still in shadow mode.

#### Scenario: Artifact does not survive redeploy

- **WHEN** the selected report is missing, unreadable or has a different SHA-256 after redeploy
- **THEN** authoritative mode SHALL NOT be configured
- **AND** the service SHALL remain in shadow

### Requirement: Activation is calibration-only and staged

The operator SHALL configure the policy path first while shadow remains effective. Only after settings, policy loader and recognizer factory load the selected artifact successfully may the operator configure `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative`. The activation SHALL target only the Railway `calibracion` environment and SHALL not use Twilio or real-message traffic.

#### Scenario: Loader rejects selected artifact

- **WHEN** the loader rejects the configured artifact
- **THEN** activation SHALL stop before authoritative mode
- **AND** no replacement policy SHALL be invented

### Requirement: Shadow rollback remains immediate

A promotion SHALL define and validate rollback by returning the calibration environment to `PRODUCT_RECOGNIZER_MODE=shadow` and redeploying. Rollback SHALL preserve the evidence artifacts and SHALL not require a database mutation.

#### Scenario: Controlled activation is unhealthy

- **WHEN** deploy or controlled validation is unhealthy after activation
- **THEN** the operator SHALL revert the mode to shadow
- **AND** no production or Twilio validation SHALL be started
