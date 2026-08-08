## MODIFIED Requirements

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

### Requirement: Provider core has separated transaction owners

The provider acceptance boundary SHALL be the sole owner of its short receipt
and inbound-work acceptance transaction. The bounded deferred processor SHALL
own a distinct transaction for each leased work item and commit business
effects, outbound rows and terminal work finalization atomically. Repositories
and reusable pipeline primitives SHALL NOT control transactions.

#### Scenario: Processing rollback keeps retryable work and removes business effects

- **WHEN** deferred business processing raises a technical failure before its
  terminal commit
- **THEN** session/pedido/pipeline/outbound effects from that turn roll back
- **AND** the work item remains safely retryable according to its bounded
  lease/backoff policy without exposing raw message text
