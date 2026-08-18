## ADDED Requirements

### Requirement: An owner completes onboarding through a private draft

The system SHALL keep incomplete registration data in an account-owned private
onboarding draft. On valid completion, one atomic application-service
transaction SHALL create an `INACTIVO` `Comercio`, its active OWNER
`ComercioUsuario` membership, and the terminal transition of that exact draft.

#### Scenario: Valid draft completion creates a non-operational commerce

- **WHEN** an authenticated owner completes every required basic commerce
  field in its authorized draft
- **THEN** the system SHALL create exactly one commerce in `INACTIVO` and its
  OWNER membership in the same transaction
- **AND THEN** it SHALL not create a channel, customer, session, order,
  catalogue row, provider work or trial reservation

#### Scenario: Completion persistence failure is atomic

- **WHEN** any persistence failure occurs while completing the draft
- **THEN** the system SHALL roll back the commerce, membership and draft
  terminal transition together
- **AND THEN** the owner SHALL be able to resume the prior authorized draft

### Requirement: Operational readiness is derived and controlled

The system SHALL show an owner a read-only readiness projection from the exact
commerce profile, eligible active payment/delivery associations, channel state,
catalogue readiness and existing lifecycle policy. An owner SHALL NOT set
`prueba_hasta`, `prueba_max_pedidos`, `prueba_pedidos_consumidos`, lifecycle
state, channel activation or a mutable "ready" flag.

#### Scenario: Missing configuration keeps the commerce unavailable

- **WHEN** one or more readiness prerequisites are absent
- **THEN** the dashboard SHALL show bounded missing requirements
- **AND THEN** the commerce SHALL remain `INACTIVO` and no inbound routing
  fallback or order acceptance SHALL occur

#### Scenario: Admin grants a configured trial

- **WHEN** Admin approves a ready commerce for trial and sets the existing
  authoritative deadline and quota
- **THEN** the commerce SHALL use the existing `PRUEBA` lifecycle semantics
- **AND THEN** confirmed-order quota reservation and all inbound availability
  guards SHALL remain unchanged
