# Capability: dedicated-railway-calibration-catalog

## Purpose

Provide a deterministic isolated Railway catalog that exactly represents the
frozen calibration dataset's business identities, without changing the
WhatsApp pilot fixture or relying on historical primary keys.

## ADDED Requirements

### Requirement: Dedicated empty-target guard

The fixture CLI SHALL operate only with an explicit non-secret dedicated-target
marker and empty fixture-owned tables, or when the exact calibration fixture is
already present. Pilot, customer, partial or unknown data SHALL return
`conflict` without mutation.

#### Scenario: Pilot catalog is rejected

- **WHEN** the target contains the WhatsApp pilot fixture or other owned data
- **THEN** verify-only reports `conflict`
- **AND** apply writes, updates and deletes no rows

### Requirement: Exact manifest coverage

The static catalog SHALL contain exactly one active product-presentation for
every controlled-calibration-manifest identity. Product, category and
presentation SHALL match literally; aliases, nearest matches, substitutions and
cross-category mappings are prohibited.

#### Scenario: Historical identity is available exactly

- **WHEN** the manifest declares Margherita or Coca-Cola
- **THEN** the catalog contains that literal active identity
- **AND** the resolver returns its runtime primary key

### Requirement: Verify-only default and atomic apply

The CLI SHALL verify read-only by default. `--apply` alone stages the fixture;
it owns one transaction, may flush once for read-back, commits once after exact
success and rolls back on every failure. Exact reruns SHALL be no-op `ready`.

#### Scenario: Mid-apply failure is atomic

- **WHEN** staging or verification fails after apply begins
- **THEN** the transaction is rolled back
- **AND** no row from that invocation persists
