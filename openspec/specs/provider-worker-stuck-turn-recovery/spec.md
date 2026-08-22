# provider-worker-stuck-turn-recovery Specification

## Purpose
TBD - created by archiving change fix-provider-worker-stuck-turn-recovery. Update Purpose after archive.
## Requirements
### Requirement: The provider worker bounds one inbound pass without changing business ownership

When automatic provider processing is enabled, the worker SHALL apply one
positive configured timeout to the existing bounded inbound CLI pass. A pass
that returns before the bound SHALL preserve the existing inbound-before-
outbound order and result. A pass that exceeds the bound SHALL fail through
the existing worker supervisor path rather than remain live indefinitely.

#### Scenario: Normal inbound pass preserves the existing cycle

- **WHEN** the bounded inbound pass returns before its configured timeout
- **THEN** the worker records the existing inbound result
- **AND THEN** it invokes the existing bounded outbound pass exactly once
- **AND THEN** it preserves the existing cycle cadence, lease ownership and
  transaction semantics

#### Scenario: A blocked inbound pass causes bounded worker recovery

- **WHEN** the inbound pass does not return before its configured timeout
- **THEN** the worker emits only the existing safe liveness failure evidence
  for the inbound phase
- **AND THEN** it does not emit a fabricated phase completion or durable
  processing outcome
- **AND THEN** it does not invoke the outbound pass in that worker process
- **AND THEN** the worker exits non-zero so the existing entrypoint
  supervisor can restart the service

#### Scenario: Timeout does not repair or finalize the leased row

- **WHEN** the worker timeout interrupts an inbound pass
- **THEN** the timeout path does not call commit, rollback, flush, close,
  lease finalization, replay or a second database connection
- **AND THEN** the existing process cleanup and lease-expiry/reclaim rules
  remain the only recovery authority

#### Scenario: Invalid timeout configuration fails closed

- **WHEN** automatic provider processing is enabled with a missing, zero,
  negative or otherwise invalid inbound timeout
- **THEN** startup validation rejects the worker configuration before traffic
  is accepted
- **AND THEN** no fallback to an unbounded worker is allowed
- **AND THEN** the error contains only the safe configuration name and
  category, never a secret or raw environment dump

#### Scenario: Timeout evidence remains privacy-safe

- **WHEN** a timeout is observed in the worker
- **THEN** its structured evidence contains only the existing closed worker
  phase/outcome vocabulary and a safe timeout exception type
- **AND THEN** it contains no message body, phone number, provider ID, URL,
  prompt, model output, credential, raw exception text or traceback

### Requirement: Existing worker phases remain unchanged outside the timeout boundary

The timeout SHALL apply only to the inbound pass boundary introduced by this
change. Readiness probing, outbound dispatch, liveness event validation and
the existing coordinator finalization policies SHALL retain their current
behavior.

#### Scenario: Outbound dispatch is not independently reimplemented

- **WHEN** an inbound pass completes normally
- **THEN** the worker invokes the existing outbound CLI through its existing
  seam
- **AND THEN** this capability does not add a second dispatcher, provider
  call, queue or retry policy
