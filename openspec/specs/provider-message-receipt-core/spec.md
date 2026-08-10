# Capability: provider-message-receipt-core

## Purpose

TBD: Provide a provider-neutral, transaction-owning boundary for idempotent inbound provider-message receipt processing.
## Requirements
### Requirement: Provider receipts are an idempotent committed boundary

The system SHALL identify inbound provider messages by the unique pair of a
normalized provider identifier and opaque provider receipt identifier. A first
valid receipt SHALL be committed in the same short transaction as exactly one
durable deferred inbound work item. A previously committed receipt SHALL return
`already_processed` and SHALL NOT create another work item or invoke business
processing.

#### Scenario: Webhook acceptance is independent of slow business processing

- **WHEN** a first valid provider receipt passes client/channel/commerce
  authority validation
- **THEN** the acceptance boundary commits the receipt and exactly one pending
  deferred inbound work item before returning the provider response
- **AND** it does not call classifier, recognizer, session/pedido staging,
  intent pipeline, response mapping or outbound staging in the webhook request

#### Scenario: Duplicate receipt does not duplicate deferred work

- **WHEN** the same provider and receipt identifier is delivered after a
  successful acceptance commit
- **THEN** the system returns `already_processed`
- **AND** it creates no second work item and invokes no business processing

#### Scenario: Duplicate receipt is not processed twice

- **WHEN** the same provider and receipt identifier is submitted after a
  successful first acceptance
- **THEN** the system returns `already_processed`
- **AND** it does not invoke the business processor or create another work item

#### Scenario: Failed processing leaves no durable receipt claim

- **WHEN** receipt validation or deferred-work acceptance raises a technical
  failure before its short transaction commits
- **THEN** the acceptance boundary rolls back the complete transaction
- **AND** a later valid retry is not treated as already processed

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

The provider acceptance boundary SHALL be the sole owner of its short receipt
and inbound-work acceptance transaction. The bounded deferred processor SHALL
own a distinct transaction for each leased work item and commit business
effects, outbound rows and terminal work finalization atomically. Repositories
and reusable pipeline primitives SHALL NOT control transactions.

#### Scenario: Successful first processing commits atomically

- **WHEN** a valid first provider receipt is processed successfully
- **THEN** the receipt, active compatible conversation session and pipeline
  effects become durable together through one commit
- **AND** no separate service/repository commit or rollback occurs

#### Scenario: Processing rollback keeps retryable work and removes business effects

- **WHEN** deferred business processing raises a technical failure before its
  terminal commit
- **THEN** session/pedido/pipeline/outbound effects from that turn roll back
- **AND** the work item remains safely retryable according to its bounded
  lease/backoff policy without exposing raw message text
