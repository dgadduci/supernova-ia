# provider-inbound-processing Specification

## Purpose
TBD - created by archiving change defer-provider-inbound-processing-7-4. Update Purpose after archive.
## Requirements
### Requirement: Inbound work is durable, bounded and privacy-limited

Each accepted provider receipt SHALL own at most one durable inbound work item.
The item SHALL retain its inbound message body only while pending, leased or
retryable processing requires it. On successful processing or terminal
exhaustion it SHALL scrub the body and retain only safe state, timestamp and
failure metadata. It SHALL NOT log or print the body.

#### Scenario: Completed work scrubs message body

- **WHEN** a leased inbound item completes the existing pipeline and stages its
  outbound responses successfully
- **THEN** its final state is `processed`, its transient body is cleared, and
  the receipt-linked outbound rows are durable in the same processing commit

### Requirement: Explicit processor preserves receipt order per conversation

The operator CLI SHALL process no more than its explicit bound and SHALL not
process a later pending item for a client/channel while an earlier item for that
conversation remains pending, leased or retryable.

#### Scenario: Later message waits for earlier retry

- **WHEN** receipt A precedes receipt B for the same client/channel and A is
  retryable
- **THEN** a bounded pass does not process B before A reaches `processed` or a
  terminal state

### Requirement: Webhook acknowledgements do not depend on LLM latency

The provider webhook SHALL return its valid receipt acknowledgement without
calling any classifier, recognizer, embedding, LLM or message pipeline surface.

#### Scenario: Slow recognizer cannot timeout the webhook

- **WHEN** downstream recognition would take longer than the provider deadline
- **THEN** the webhook has already committed the receipt/work item and returned
  its acknowledgement
- **AND** the explicit processor handles recognition later

### Requirement: Deferred processing ensures a draft pedido before the pipeline

The bounded deferred processor SHALL acquire or stage the active conversation session for the accepted receipt before calling the existing message pipeline. When that session has no `id_pedido`, the processor SHALL stage exactly one `borrador` pedido, associate its generated ID to the same session, and then invoke the pipeline. When the session already has an `id_pedido`, the processor SHALL NOT create, replace, or reassociate a pedido. The session, any newly staged pedido and association, pipeline effects, outbound rows, and work-item finalization SHALL become durable only through the processor's one final commit.

#### Scenario: First deferred processing creates the missing draft pedido

- **WHEN** a leased accepted receipt is processed and its acquired or staged active session has no `id_pedido`
- **THEN** exactly one `borrador` pedido is staged and associated to that session before the existing message pipeline runs
- **AND** the session, pedido, association, pipeline effects, outbound rows, and processed work state become durable through the processor's final commit

#### Scenario: Existing orderless session receives one draft pedido

- **WHEN** a leased accepted receipt resolves an existing active session whose `id_pedido` is null
- **THEN** the processor stages and associates exactly one `borrador` pedido before the existing message pipeline runs

#### Scenario: Existing pedido association remains unchanged

- **WHEN** a leased accepted receipt resolves an active session whose `id_pedido` is already non-null
- **THEN** the processor does not create, replace, or reassociate a pedido
- **AND** existing message processing continues

#### Scenario: Technical failure rolls back newly staged business effects

- **WHEN** session/pedido staging, pipeline processing, or outbound staging raises a technical failure before the processor commit
- **THEN** the processor rolls back newly staged session, pedido, association, pipeline, and outbound effects
- **AND** existing bounded failure handling retains or finalizes the work item according to its retry policy

### Requirement: Provider inbound acceptance uses the centralized commerce availability policy

Before accepting or routing provider inbound work for a commerce, the system
SHALL evaluate the centralized availability policy. It SHALL reject blocked,
missing, expired-trial, and quota-exhausted commerce without choosing a
different commerce or creating a replacement order.

#### Scenario: Expired trial is rejected before new work is accepted

- **WHEN** inbound provider work resolves to a commerce whose PRUEBA deadline
  has passed
- **THEN** the result is a typed unavailable-commerce outcome
- **AND** no receipt-derived order/session work for that commerce is created

### Requirement: Provider leased processing re-evaluates commerce availability

Before leased provider work stages a session, draft, intent, or outbound row,
the system SHALL evaluate the centralized policy using the commerce id in its
claimed receipt. Acceptance-time availability does not authorize later work.
Unavailable work SHALL be finalized non-retryable with a bounded policy reason;
it SHALL not invoke the pipeline or stage session, draft, order, or outbound
work. Technical evaluation failure retains existing rollback/retry behavior and
shall not process the message.

#### Scenario: Commerce becomes inactive after acceptance

- **GIVEN** provider work was accepted while available
- **AND** the commerce becomes blocked before lease processing
- **WHEN** the worker processes the lease
- **THEN** it is finalized unavailable and non-retryable
- **AND** no session, draft, intent, or outbound message is staged

### Requirement: Every current inbound entry point uses the centralized policy

The authenticated direct/test incoming-message endpoint SHALL evaluate the
same policy before loading a session or invoking the response orchestrator.
Unavailable commerce SHALL receive a bounded unavailable-commerce HTTP error
and SHALL not mutate business state or generate a customer response. Current
and future channel adapters SHALL delegate lifecycle interpretation to
`CommerceAvailabilityService`, never code, description, or label branches.

#### Scenario: Direct/test message to inactive commerce is rejected

- **WHEN** an authenticated direct/test request targets a blocked commerce
- **THEN** it returns the bounded unavailable-commerce error
- **AND** it does not load a session or invoke the response orchestrator
