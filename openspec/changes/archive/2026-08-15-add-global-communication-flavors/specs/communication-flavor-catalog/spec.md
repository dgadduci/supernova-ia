## ADDED Requirements

### Requirement: Communication flavors are a global controlled catalog

The system SHALL persist communication flavors globally, not per commerce. A
flavor SHALL have a unique stable code, visible name, administrator-facing
description, internal LLM instruction, active flag and version. The internal
LLM instruction SHALL be system-managed and SHALL NOT be accepted as commerce
input or returned through any read API.

#### Scenario: Safe active flavor listing excludes the internal instruction

- **WHEN** an authenticated administrator lists available communication flavors
- **THEN** each returned flavor includes its safe identifier, code, name,
  description, version and active state
- **AND THEN** no returned object contains `instruccion_llm`.

### Requirement: Canonical neutral flavor is available

The global catalog SHALL contain exactly one active canonical flavor whose code
is `neutro` before any commerce association is required.

#### Scenario: Neutral seed is resolved by code during migration

- **WHEN** the flavor migration runs against an existing database
- **THEN** it resolves the canonical `neutro` flavor by code
- **AND THEN** it does not rely on a fixed numeric flavor ID.
