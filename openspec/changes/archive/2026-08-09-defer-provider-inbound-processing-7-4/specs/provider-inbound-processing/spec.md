## ADDED Requirements

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
