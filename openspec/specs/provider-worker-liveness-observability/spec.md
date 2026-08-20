# provider-worker-liveness-observability Specification

## Purpose
TBD - created by archiving change add-provider-worker-liveness-observability. Update Purpose after archive.
## Requirements
### Requirement: Worker phase progress is observable without changing work semantics

The provider-processing worker SHALL emit a privacy-safe structured
`provider_worker_liveness` event for cycle start and completion and for the
readiness, inbound, outbound and sleep phase boundaries. The event SHALL use
only the catalogued lifecycle outcome, phase, bounded cycle index, bounded
duration and safe technical metadata.

#### Scenario: Normal ready cycle preserves the existing order

- **WHEN** the readiness gate is ready and a worker cycle runs
- **THEN** the worker emits `cycle_started`, then inbound phase-start and
  phase-completion evidence before outbound phase-start evidence
- **AND THEN** the existing bounded outbound pass runs exactly once
- **AND THEN** sleep and cycle-completion evidence are emitted according to
  the existing cadence

#### Scenario: Readiness gate skips inbound without hiding outbound

- **WHEN** the readiness probe reports not-ready for a cycle
- **THEN** the worker records the readiness phase outcome and does not invoke
  the inbound pass
- **AND THEN** it invokes and instruments the existing bounded outbound pass
- **AND THEN** it does not create, release or retry inbound work because of
  the liveness instrumentation

### Requirement: An incomplete phase is diagnosable but does not trigger an unsafe recovery

The worker SHALL emit a phase-start event before invoking each potentially
long-running readiness, inbound, outbound or sleep seam. It SHALL emit a
matching phase-completion event only after that seam returns. If the seam
raises, it SHALL emit a phase-failure event with only safe exception metadata
and SHALL preserve the existing re-raise and supervisor behavior. The absence
of a completion event SHALL NOT by itself cause the worker to invent a retry,
release a lease, skip a phase or terminate the process.

#### Scenario: Inbound pass does not return

- **WHEN** the worker has emitted `phase_started` for `inbound` and the
  existing inbound pass has not returned
- **THEN** no fabricated `phase_completed`, business outcome or recovery event
  is emitted for that phase
- **AND THEN** existing transaction, lease and retry ownership remains
  unchanged

#### Scenario: Outbound pass raises a technical exception

- **WHEN** the existing outbound pass raises unexpectedly
- **THEN** the worker emits `phase_failed` for `outbound` with a closed
  technical category and safe exception type only
- **AND THEN** the exception continues through the existing supervisor path
  so the service restart behavior remains unchanged

### Requirement: Liveness events are privacy-safe and bounded

The `provider_worker_liveness` event SHALL reject unknown fields, free-form
phase/outcome values, unbounded numeric values and sensitive payloads. It SHALL
NOT contain message bodies, phone numbers, provider identifiers or payloads,
prompts, model output, URLs, credentials, tokens, raw exception messages or
tracebacks. Event validation or serialization failure SHALL NOT change the
underlying worker business path.

#### Scenario: Liveness evidence round-trips through production log parsing

- **WHEN** a valid liveness event is serialized and parsed by the existing
  production-observability parser
- **THEN** it round-trips as the same safe structured event
- **AND THEN** an event with a forbidden field or value is rejected without
  printing the raw line