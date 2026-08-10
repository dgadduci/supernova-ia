# Capability: automatic-provider-processing-worker

## ADDED Requirements

### Requirement: Provider processing automation is explicit and reversible

The system SHALL start an automatic provider-processing worker only when
`PROVIDER_PROCESSING_WORKER_ENABLED` is explicitly enabled. When disabled, no
automatic polling or provider dispatch SHALL occur and the existing manual
inbound/outbound CLIs SHALL remain usable. Enabling the worker with invalid
worker or existing outbound configuration SHALL fail startup before the web
application receives traffic.

#### Scenario: Disabled deployment retains manual operation

- **WHEN** `PROVIDER_PROCESSING_WORKER_ENABLED=false`
- **THEN** the entrypoint starts no worker process
- **AND** valid webhook receipts remain durable pending work for the existing
  manual CLIs

#### Scenario: Invalid enabled configuration fails safely

- **WHEN** the worker flag is enabled and one configured bound or interval is
  non-positive, or outbound configuration is invalid
- **THEN** startup fails before `uvicorn` accepts traffic
- **AND** it does not silently disable the worker or create a second pipeline

### Requirement: Each automatic cycle delegates to existing bounded passes

Each worker cycle SHALL invoke the existing bounded inbound-processing CLI pass
before the existing bounded outbound-dispatch CLI pass, using strictly positive
configured bounds. The worker SHALL NOT perform direct database claims, direct
provider sends, business transaction control, or inline webhook processing.

#### Scenario: Accepted receipt reaches existing outbox automatically

- **WHEN** a valid webhook commits an inbound work item while the worker is
  enabled
- **THEN** a subsequent bounded cycle invokes the existing inbound processor
  before outbound dispatch
- **AND** any resulting response is staged and dispatched through the existing
  lease-protected outbox contracts

### Requirement: Existing durable recovery behavior remains authoritative

No-due, retryable and terminal outcomes from existing passes SHALL be treated
as normal cycle outcomes. An unexpected worker failure SHALL be visible through
safe operational logging and cause its entrypoint supervisor to terminate the
service for Railway restart. Existing lease expiration, conditional
finalization, retry bounds and per-conversation ordering remain authoritative.

#### Scenario: Retryable row does not stop automation or duplicate work

- **WHEN** an inbound or outbound pass produces a retryable outcome
- **THEN** the worker continues with later scheduled cycles
- **AND** it does not alter lease, retry or ordering semantics outside the
  existing pass implementation

### Requirement: Worker observability excludes customer and provider secrets

Worker logs SHALL contain only derived counts, outcomes, durations and configured
bounds. They SHALL NOT contain inbound/outbound bodies, customer addresses,
LLM content, provider signatures, provider URLs, account identifiers, tokens
or environment dumps.

#### Scenario: Empty cycle is observable without content disclosure

- **WHEN** neither pass finds due work
- **THEN** the worker may emit a safe empty-cycle record and waits its configured
  interval
- **AND** that record contains no customer or provider payload content
