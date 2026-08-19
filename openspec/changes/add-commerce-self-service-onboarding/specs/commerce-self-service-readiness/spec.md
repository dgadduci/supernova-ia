## ADDED Requirements

### Requirement: An owner completes onboarding through a private draft

The system SHALL keep incomplete registration data in an account-owned private
onboarding draft. On valid completion, one atomic, caller-owned application
transaction SHALL create an `INACTIVO` `Comercio`, its active
OWNER `ComercioUsuario` membership, and the terminal transition of that exact
draft. The draft SHALL contain the required validated immutable `slug` before
completion.

#### Scenario: Valid draft completion creates a non-operational commerce

- **WHEN** an authenticated owner completes every required basic commerce
  field, including `slug`, in its authorized draft
- **THEN** the system SHALL create exactly one commerce in `INACTIVO` and its
  OWNER membership in the same transaction
- **AND THEN** it SHALL not create a channel, customer, session, order,
  catalogue row, payment association, delivery association, provider work,
  readiness flag or trial reservation

#### Scenario: Incomplete or invalid draft remains resumable

- **WHEN** the exact account-owned draft is incomplete or has an invalid slug,
  duplicate routing value or other existing commerce validation error
- **THEN** the system SHALL preserve the draft and create no commerce,
  membership or terminal transition
- **AND THEN** it SHALL show a bounded correction outcome without falling back
  to another account, draft, slug or lifecycle state

#### Scenario: Concurrent completion is idempotent

- **WHEN** two authenticated requests concurrently complete the same draft
- **THEN** the draft lock and database constraints SHALL allow exactly one
  commerce and one OWNER membership
- **AND THEN** the later request SHALL return the exact terminal result rather
  than create a second commerce

#### Scenario: Terminal persistence is caller-owned and atomic

- **WHEN** a persistence failure occurs after any completion row has been
  staged but before the caller commits
- **THEN** the caller-owned rollback SHALL remove the commerce, membership and
  terminal draft transition together
- **AND THEN** the owner SHALL be able to resume the prior draft

### Requirement: Operational readiness is derived and controlled

The system SHALL show an owner a read-only readiness projection from the exact
commerce profile, eligible active payment/delivery associations, channel state
and existing lifecycle policy. Phase 4B SHALL derive the exact commerce from
the authenticated account's terminal draft and active `OWNER` membership; it
SHALL NOT accept a browser-selected commerce id. An eligible payment/delivery
association SHALL require both an active commerce bridge row and an active
global catalog row. Catalogue readiness is deferred because no authoritative
catalogue-readiness contract exists. An owner SHALL NOT set
`prueba_hasta`, `prueba_max_pedidos`, `prueba_pedidos_consumidos`, lifecycle
state, channel activation, payment/delivery association or a mutable "ready"
flag.

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
