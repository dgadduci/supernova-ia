# Capability: post-4-12b-production-verification

## Purpose

Verify the deployed post-4.12B product-recognition state through staged, privacy-safe evidence before any synchronization, deployment or environment mutation.

## ADDED Requirements

### Requirement: Historical promotion evidence is not current-state evidence

An operator SHALL treat archived Railway promotion records as historical context only. Before making a decision about the deployed state, the operator SHALL obtain fresh evidence from an explicitly identified project, environment and service after a separate authorization for that read-only gate.

#### Scenario: Fresh deployment identity is unavailable

- **WHEN** the deployed revision or target identity cannot be verified
- **THEN** no synchronization, mode change or deployment decision SHALL be derived from the archived evidence
- **AND** the operational phase SHALL stop.

### Requirement: Configuration and policy verification is staged and sanitized

Before interpreting an authoritative hybrid state, the operator SHALL verify the configured/effective recognizer modes and, when applicable, a persistent policy path with readable eligible JSON and a recorded SHA-256. Evidence SHALL exclude environment values, report content, credentials, customer data and raw exceptions.

#### Scenario: Policy or loader gate fails

- **WHEN** the policy is missing, changed, ineligible or rejected by the existing loader
- **THEN** the operator SHALL stop before any mode mutation
- **AND** no replacement policy or configuration correction SHALL be made.

### Requirement: Health and observability do not prove business recognition

The operator SHALL treat a successful `/health` response as liveness only and shall use only bounded, privacy-safe observability for technical context. Absent logs, a health success or a technical event SHALL NOT be interpreted as a product-recognition business outcome or as authorization to send traffic.

#### Scenario: Observability cannot be safely queried

- **WHEN** the available surface would reveal raw log lines or cannot provide the required bounded sanitized view
- **THEN** the observability gate SHALL stop
- **AND** no alternative traffic or customer-data probe SHALL be used.

### Requirement: Rollback remains an explicitly authorized shadow operation

If a later authorized operational decision requires rollback, it SHALL set only the approved target to `shadow`, preserve the policy artifact and its evidence, and re-verify factory and health. This verification change itself SHALL NOT mutate Railway.

#### Scenario: A verification gate finds an unhealthy state

- **WHEN** a freshly authorized gate reports unhealthy deploy, factory or health evidence
- **THEN** the operator SHALL stop and request separate authorization before changing the mode or redeploying
- **AND** Fuzzy remains the defined safe fallback.
