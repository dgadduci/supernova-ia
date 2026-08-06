# Capability: provider-message-receipt-core

## ADDED Requirements

### Requirement: Provider receipts are an idempotent committed boundary

The system SHALL identify inbound provider messages by the unique pair of a
normalized provider identifier and opaque provider receipt identifier. A first
valid receipt SHALL be claimed and committed in the same transaction as the
resulting conversation-session and existing message-pipeline effects. A
previously committed receipt SHALL return `already_processed` and SHALL NOT
invoke the pipeline, create a session or stage further business mutations.

#### Scenario: Duplicate receipt is not processed twice

- **WHEN** the same provider and receipt identifier are submitted after a
  successful first processing
- **THEN** the system returns `already_processed`
- **AND** it does not invoke the existing message pipeline or create another
  conversation session

#### Scenario: Failed processing leaves no durable receipt claim

- **WHEN** receipt claim, session staging or pipeline processing raises a
  technical failure before commit
- **THEN** the coordinator rolls back the complete transaction and propagates
  the failure
- **AND** a later valid retry is not treated as an already processed receipt

### Requirement: Provider core processes only authoritative routing decisions

The provider-neutral inbound core SHALL accept only a supplied active routing
decision for an existing active client, an active channel and an authoritative
commerce. A dedicated channel authority is its direct active commerce; a
shared channel authority is its existing selected context for the same channel
and client AND an active `ComercioCanalCompartido` membership for the same
channel and selected commerce. A pending switch target SHALL NOT be processing
authority. A revoked or missing membership on the shared channel SHALL NOT be
processing authority even when the customer-channel context still references
the commerce.

#### Scenario: Pending shared target cannot process a message

- **WHEN** a shared customer-channel context has no selected commerce or only
  a pending switch target for the supplied commerce
- **THEN** the core returns `invalid_context`
- **AND** it creates no receipt, session or pipeline effect

#### Scenario: Revoked shared membership cannot process a message

- **WHEN** the selected commerce no longer has an active
  `ComercioCanalCompartido` for the same shared channel
- **THEN** the core returns `invalid_context`
- **AND** it creates no receipt, session or pipeline effect
- **AND** the customer-channel context row is left unchanged

### Requirement: Provider core has one transaction owner

The provider-message coordinator SHALL be the sole owner of transaction
completion for provider receipt processing. It SHALL commit once only after
receipt, compatible conversation session and existing pipeline work succeed,
and SHALL roll back on technical failure. Repositories, routing services,
session staging helpers and the reusable pipeline primitive SHALL NOT control
the transaction.

#### Scenario: Successful first processing commits atomically

- **WHEN** a valid first provider receipt is processed successfully
- **THEN** the receipt, active compatible conversation session and pipeline
  effects become durable together through one commit
- **AND** no separate service/repository commit or rollback occurs
