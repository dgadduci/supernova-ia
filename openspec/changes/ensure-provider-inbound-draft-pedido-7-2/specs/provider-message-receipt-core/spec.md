## MODIFIED Requirements

### Requirement: Provider receipts are an idempotent committed boundary

The system SHALL identify inbound provider messages by the unique pair of a
normalized provider identifier and opaque provider receipt identifier. A first
valid receipt SHALL be claimed and committed in the same transaction as the
resulting compatible conversation-session, its associated draft pedido when
the session did not already have one, and existing message-pipeline effects. A
previously committed receipt SHALL return `already_processed` and SHALL NOT
invoke the pipeline, create a session, create a pedido, or stage further
business mutations.

#### Scenario: First receipt creates the missing draft pedido atomically

- **WHEN** a first valid provider receipt acquires or stages an active session
  whose `id_pedido` is null
- **THEN** exactly one `borrador` pedido is staged for that session and its ID
  is associated to the session before the existing message pipeline runs
- **AND** receipt, session, pedido, association, pipeline effects and outbound
  rows become durable only through the coordinator's one final commit

#### Scenario: Existing pedido association remains unchanged

- **WHEN** a first valid provider receipt acquires an active session whose
  `id_pedido` is already non-null
- **THEN** the coordinator does not create, replace, or reassociate a pedido
- **AND** existing processing continues unchanged

#### Scenario: Failed processing leaves no draft pedido

- **WHEN** receipt claim, session/pedido staging, pipeline processing, or
  outbox staging raises a technical failure before commit
- **THEN** the coordinator rolls back the complete transaction and propagates
  the failure
- **AND** no newly staged receipt, session, pedido, association, or pipeline
  effect remains durable
- **AND** a later valid retry is not treated as an already processed receipt
