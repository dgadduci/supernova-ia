## MODIFIED Requirements

### Requirement: Worker phase progress is observable without changing work semantics

The provider-processing worker SHALL emit a privacy-safe structured
`provider_worker_liveness` event for cycle start and completion and for the
readiness, inbound, inbound-runner, outbound, cycle-summary and sleep phase
boundaries. The event SHALL use only the catalogued lifecycle outcome, phase,
bounded cycle index, bounded duration and safe technical metadata.

#### Scenario: Normal ready cycle exposes nested worker boundaries

- **WHEN** the readiness gate is ready and a worker cycle runs
- **THEN** the worker emits `cycle_started`, then inbound phase-start evidence
- **AND THEN** it emits `inbound_runner` phase-start only after the existing
  inbound timeout is armed and before invoking the existing inbound runner
- **AND THEN** it emits inbound-runner and inbound completion only after their
  respective existing seams return
- **AND THEN** it emits the existing outbound phase evidence exactly once
- **AND THEN** it emits `cycle_summary` phase-start and completion around the
  existing summary writer before `cycle_completed`
- **AND THEN** sleep and the next-cycle evidence retain the existing cadence

#### Scenario: Inbound runner does not return

- **WHEN** the worker has emitted `phase_started` for `inbound_runner` and the
  existing inbound runner does not return
- **THEN** it emits no fabricated completion for `inbound_runner` or `inbound`
- **AND THEN** it does not invoke outbound processing in that worker process
- **AND THEN** existing timeout, supervisor, transaction and lease behavior
  remains authoritative

#### Scenario: Summary writer raises

- **WHEN** the existing cycle summary writer raises unexpectedly
- **THEN** the worker emits `phase_failed` for `cycle_summary` with only safe
  exception metadata
- **AND THEN** it does not emit a fabricated cycle completion
- **AND THEN** the exception continues through the existing supervisor path

### Requirement: An incomplete phase is diagnosable but does not trigger an unsafe recovery

The worker SHALL emit a phase-start event before invoking each potentially
long-running readiness, inbound, inbound-runner, outbound, cycle-summary or
sleep seam. It SHALL emit a matching phase-completion event only after that
seam returns. If the seam raises, it SHALL emit a phase-failure event with only
safe exception metadata and SHALL preserve the existing re-raise and
supervisor behavior. The absence of a completion event SHALL NOT by itself
cause the worker to invent a retry, release a lease, skip a phase, terminate
the process or trigger automatic recovery.

#### Scenario: Missing worker-progress evidence remains observational

- **WHEN** a liveness trace ends at any worker phase boundary
- **THEN** the last completed or started boundary is usable only as diagnostic
  evidence for the next investigation
- **AND THEN** no watchdog, restart action, replay, timeout or failure outcome
  is inferred or produced solely from the missing later event
