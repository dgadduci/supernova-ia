# Capability: controlled-railway-fixtures

## Purpose

Provide a deterministic, safe, manually invoked fixture dataset for an empty
production-shaped database, so the project can exercise catalog and dedicated
WhatsApp pilot behavior without importing, reading, cleaning, or changing a
local business database.

## ADDED Requirements

### Requirement: Deterministic three-commerce fixture dataset

The system SHALL define exactly three synthetic active commerce fixtures with
stable slugs `piloto-whatsapp-dedicado`,
`piloto-whatsapp-compartido-uno`, and
`piloto-whatsapp-compartido-dos`. Each fixture SHALL contain the same four
categories, seven presentations, thirty fixed products, valid category-driven
product-presentation associations, and one fixed price per association.

#### Scenario: Fixture shape is complete

- **WHEN** the controlled fixture dataset has been applied successfully
- **THEN** each fixture commerce has four categories, seven presentations,
  thirty products, fifty-nine product-presentations, and fifty-nine prices
- **AND** every fixture commerce state is `ACTIVO`

#### Scenario: Presentation policy is enforced by fixture data

- **WHEN** the fixture product-presentations are inspected
- **THEN** every pizza has only `grande` and `chica`
- **AND** every empanada has only `unidad`
- **AND** every beverage has only `lata`, `litro`, and `2-litros`
- **AND** every dessert has only `unidad` and `kilo`

### Requirement: Empty-target guard and controlled verification/apply boundary

The system SHALL expose an internal CLI whose default mode is read-only
verification and whose mutating behavior requires explicit `--apply`. Fixture
definitions SHALL be static application data; the CLI SHALL NOT read, export,
clean, reset, or otherwise access a local source database. Before its first
apply, every fixture-owned table (commerce states, commerces, categories,
presentations, products, product-presentations, and prices) SHALL be empty.
Exact, complete existing fixture data SHALL return `ready` without mutation.
An empty compatible fixture namespace SHALL return `not_ready` in verification
and may return `provisioned` only after explicit apply.

#### Scenario: Default invocation never mutates

- **WHEN** the fixture CLI is invoked without `--apply`
- **THEN** it performs no insert, update, delete, flush, commit, or rollback
- **AND** it reports only a safe status and aggregate fixture information

#### Scenario: Exact rerun is a no-op

- **WHEN** the complete exact fixture set already exists and the CLI is
  invoked with `--apply`
- **THEN** it returns `ready`
- **AND** it does not mutate any row

#### Scenario: Existing local or target catalog is rejected safely

- **WHEN** verification finds any pre-existing row in a fixture-owned table
  before the exact fixture set exists
- **THEN** it reports a conflict and performs no mutation
- **AND** explicit apply does not clean, overwrite, merge, or reseed that
  database

### Requirement: Existing business data is never repaired implicitly

The CLI SHALL refuse a stable fixture identity that conflicts with the defined
fixture shape. It SHALL not overwrite, delete, reassociate, or silently merge
an existing commerce, category, presentation, product, association, or price.

#### Scenario: Conflicting stable commerce is safe

- **WHEN** a commerce already exists under a fixture slug with incompatible
  fixture attributes
- **THEN** verification reports a conflict
- **AND** explicit apply persists no fixture mutation

### Requirement: Dedicated routing is separate and shared routing is deferred

The fixture CLI SHALL NOT create or modify a `CanalWhatsapp`, shared-channel
membership, routing code, client, message, session, or order. The existing
dedicated-routing provisioner remains the sole surface that may bind the
configured real Twilio sender to the active dedicated fixture commerce after
the fixture dataset is ready.

#### Scenario: Fixture apply does not create transport routing data

- **WHEN** the fixture CLI applies its dataset
- **THEN** no WhatsApp channel, shared membership, routing code, or client is
  created
- **AND** the two shared-labelled fixture commerces remain catalog-only until
  a separate approved shared-routing change has a second real destination

### Requirement: Single transaction and sanitized observability

The CLI SHALL own one transaction. Helpers SHALL not call `commit`,
`rollback`, `begin`, or `flush`; the CLI MAY flush once for final verification
and SHALL commit once only after success or roll back on failure. Command
output and errors SHALL exclude database URLs, credentials, E.164 values,
message bodies, signatures, and raw caught exception text.

#### Scenario: Mid-apply failure leaves no partial fixture dataset

- **WHEN** a staging or final verification failure occurs during explicit
  apply
- **THEN** the CLI rolls back its transaction
- **AND** none of that invocation's fixture rows persist
