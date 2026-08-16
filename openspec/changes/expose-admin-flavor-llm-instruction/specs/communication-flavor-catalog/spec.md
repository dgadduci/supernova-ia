## MODIFIED Requirements

### Requirement: Communication flavors are a global controlled catalog

The system SHALL persist communication flavors globally, not per commerce. A
flavor SHALL have a unique stable code, visible name, administrator-facing
description, internal LLM instruction, active flag and version. The internal
LLM instruction SHALL be system-managed, SHALL NOT be accepted as commerce
input, and SHALL be returned only by the existing authenticated global flavor
catalog listing. It SHALL NOT be returned through commerce or configuration
read models.

#### Scenario: Authenticated catalog listing includes the internal instruction

- **WHEN** an authenticated administrator lists available communication flavors
- **THEN** each returned active flavor includes its identifier, code, name,
  description, `instruccion_llm`, version and active state
- **AND THEN** `instruccion_llm` equals the persisted value for that flavor.

#### Scenario: Commerce projections exclude the internal instruction

- **WHEN** a commerce or commerce configuration is read, or a flavor is
  assigned to a commerce
- **THEN** the nested flavor projection does not contain `instruccion_llm`.

#### Scenario: Unauthenticated callers cannot read the catalog instruction

- **WHEN** the global flavor catalog is requested without a valid
  administrative token
- **THEN** the existing generic authentication rejection is returned
- **AND THEN** neither an instruction nor an instruction-derived error detail
  is returned.
