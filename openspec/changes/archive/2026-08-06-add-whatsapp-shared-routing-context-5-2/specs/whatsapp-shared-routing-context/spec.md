# Capability: whatsapp-shared-routing-context

## Purpose

Safely select a commerce for a known client on a shared WhatsApp destination
without entering the order pipeline or silently switching commerce.

## ADDED Requirements

### Requirement: Customer context is channel-scoped and durable

The system SHALL persist at most one customer routing context per
`(canal_id, cliente_id)`. It SHALL be independent of `Session`, retain the
selected commerce and an optional exact pending original message, and use
restrictive foreign keys to the channel, existing client and selected commerce.

#### Scenario: One client uses two destinations

- **WHEN** the same existing client activates commerce selection on two
  different shared channels
- **THEN** the selections are stored and retrieved independently

### Requirement: Shared-code activation is exact and commerce-isolated

The activation service SHALL normalize a routing code and select a commerce
only from an active membership matching both the supplied active shared channel
and that normalized code. It SHALL require the supplied client and membership
commerce to exist and be active.

#### Scenario: Valid initial code activates one commerce

- **WHEN** a known active client supplies a valid active code for an active
  shared channel with no prior selection
- **THEN** the context selects only the membership commerce

#### Scenario: Missing or inactive client cannot activate routing

- **WHEN** a caller supplies a nonexistent or inactive client with otherwise
  valid shared routing input
- **THEN** activation returns `invalid_context` and creates or updates no
  customer-channel context

#### Scenario: Revoked or foreign code selects no commerce

- **WHEN** a code is revoked, unknown, or belongs to another channel
- **THEN** activation returns a typed non-selected outcome and leaves context
  selection unchanged

### Requirement: Original text is preserved before pipeline processing

On first successful activation, the system SHALL persist the raw original text
unchanged as pending context input. It SHALL NOT invoke the local endpoint,
create a session/order, or call classifier, recognizer, handler or catalog
code.

#### Scenario: Code does not become classifier input

- **WHEN** a valid code activates a commerce selection
- **THEN** the exact original text remains pending and no business pipeline is
  invoked

### Requirement: Selection never silently switches commerce

If a context already selects a commerce, the same matching code SHALL return
an idempotent `already_selected` outcome without overwriting its pending text.
A different valid code SHALL return `requires_explicit_switch` and SHALL NOT
change the selection or pending text.

#### Scenario: Conflicting valid code requires a later confirmation

- **WHEN** an already selected client supplies a code for another commerce
- **THEN** no state changes and the result requires explicit switch handling

### Requirement: Phase-5.2 preserves caller transaction ownership

The Phase-5.2 service and its repository SHALL NOT invoke `commit`, `rollback`,
`begin`, or `flush`. The caller SHALL own persistence synchronization and
transaction completion.

The service SHALL NOT translate an `IntegrityError` from pending context
insertion into a business outcome; concurrent receipt conflict and idempotency
are deferred to Phase 5.4.

#### Scenario: Activation leaves synchronization to the caller

- **WHEN** activation creates or updates context state
- **THEN** no Phase-5.2 component invokes transaction-control methods
