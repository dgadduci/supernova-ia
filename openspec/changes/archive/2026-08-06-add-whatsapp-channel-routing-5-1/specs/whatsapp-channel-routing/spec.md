# Capability: whatsapp-channel-routing

## Purpose

Define durable, commerce-isolated routing for WhatsApp providers. It identifies
a destination channel before order-pipeline work and implements dedicated
channels now while retaining the approved shared-context, idempotency and
validated-webhook constraints for later Phase-5 deltas.

## ADDED Requirements

### Requirement: Canonical WhatsApp channel identity

The system SHALL persist a WhatsApp channel independently of
`Comercio.whatsapp`, identified uniquely by provider and canonical E.164
destination number without a transport prefix. Credentials and Twilio secrets
SHALL NOT be persisted in channel or commerce tables.

The declarative model metadata SHALL declare the same active-only partial
unique provider/destination index created by the migration, so metadata and
database schema retain one canonical identity constraint.

#### Scenario: Equivalent representations have one identity

- **WHEN** a caller supplies equivalent supported destination representations
- **THEN** normalization yields the same canonical channel identity

#### Scenario: Provider identity prevents conflation

- **WHEN** two providers use the same canonical destination number
- **THEN** each provider-scoped channel remains independently addressable

#### Scenario: Metadata preserves the active identity constraint

- **WHEN** migration metadata is compared with the declarative model
- **THEN** the named active-only provider/destination unique index is present
  in both representations

### Requirement: Dedicated and shared channels have distinct ownership

A dedicated channel SHALL have exactly one exclusive commerce reference while
active. A shared channel SHALL have no exclusive commerce reference and MAY
have memberships only through the shared-channel association. A membership for
a dedicated channel SHALL be rejected.

#### Scenario: Dedicated channel resolves its exclusive commerce

- **WHEN** an active dedicated channel has an active exclusive commerce
- **THEN** dedicated resolution identifies that one commerce

#### Scenario: Shared channel cannot masquerade as dedicated

- **WHEN** a channel is shared
- **THEN** it has no exclusive commerce reference and dedicated resolution
  does not select a commerce

### Requirement: Shared routing codes are opaque and non-reassignable

Each shared membership SHALL reserve an opaque normalized public code unique
across the full channel history. Deactivating a code SHALL revoke it and SHALL
NOT permit its value to identify another commerce.

#### Scenario: Revoked code remains reserved

- **WHEN** a shared routing code is deactivated
- **THEN** assigning the same channel/code value to another commerce is
  rejected

### Requirement: Dedicated resolution is pure and pre-pipeline

The resolver SHALL accept provider and destination and return a typed outcome.
It SHALL resolve an active dedicated channel only when its exclusive commerce
is active. It SHALL NOT create a client/context/session; read message text;
invoke classifier, recognizer, handler or catalog code; or commit, roll back
or otherwise own a transaction.

#### Scenario: Inactive destination does not reach business processing

- **WHEN** a channel or exclusive commerce is inactive
- **THEN** the resolver returns a non-resolved typed outcome and invokes no
  commerce business pipeline

#### Scenario: Shared destination waits for later routing

- **WHEN** an active shared channel is supplied to dedicated resolution
- **THEN** it returns `requires_shared_routing` without selecting a commerce

### Requirement: Phase-5.1 persistence preserves transaction ownership

The channel lifecycle service and repositories for the two new channel tables
SHALL add or modify caller-owned ORM state without invoking `commit`,
`rollback`, `begin`, or `flush`. The caller SHALL own transaction control and
may flush or commit after the service returns.

#### Scenario: Registration leaves synchronization to the caller

- **WHEN** a caller registers or deactivates a channel or shared membership
- **THEN** the Phase-5.1 service/repository path invokes none of `commit`,
  `rollback`, `begin`, or `flush`

### Requirement: Cross-phase commerce-routing safety

Any later inbound-processing extension SHALL resolve commerce before the
business pipeline; identify context by `(canal, cliente)`; preserve unresolved
original text; prevent automatic commerce switching; scope every data access by
resolved commerce; deduplicate provider messages before mutation; validate
provider signatures before mutation; keep secrets outside the database; and
process each inbound message in one transaction.

#### Scenario: Future conflicting code cannot silently switch commerce

- **WHEN** a customer has an active routed order and supplies another commerce
  code
- **THEN** the later extension requires explicit switch/cancel confirmation

#### Scenario: Future provider retry cannot duplicate a mutation

- **WHEN** a provider retries one immutable message identifier
- **THEN** the later extension returns the persisted outcome without duplicate
  session, order mutation or commercial reply
