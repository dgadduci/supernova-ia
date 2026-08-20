# Tasks: provider worker liveness observability

## OpenSpec and event contract

- [x] 1.1 Add the `provider_worker_liveness` event and closed outcome/phase
  allowlists to the shared observability catalogue.
- [x] 1.2 Validate required fields, bounds and forbidden fields, and preserve
  the existing production-log parser behavior for all other events.
- [x] 1.3 Add the capability spec delta under
  `specs/provider-worker-liveness-observability/spec.md`.

## Worker instrumentation

- [x] 2.1 Emit cycle-start evidence before readiness/processing work begins.
- [x] 2.2 Emit readiness phase start/completion evidence without changing the
  existing not-ready gate or outbound continuity.
- [x] 2.3 Emit inbound and outbound phase start/completion evidence while
  preserving the existing bounded pass order and injectable seams.
- [x] 2.4 Emit sleep phase evidence and cycle completion only after the current
  summary path returns; emit phase failure evidence before re-raising an
  unexpected exception.
- [x] 2.5 Ensure event failures cannot change business outcomes, lease state,
  retries or process-supervisor behavior.

## Focused tests and validation

- [x] 3.1 Cover event catalogue round-trip, invalid phase/outcome, bounds and
  sensitive-field rejection.
- [x] 3.2 Cover normal ready, not-ready, phase-failure and incomplete-phase
  worker paths with no real sleep, database or provider call.
- [x] 3.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check` using the exact commands in the proposal.
- [x] 3.4 Report changed files, complete validation output, unresolved
  limitations and confirm that sync/archive were not performed.

## Explicitly out of scope

- [x] 4.1 Do not add automatic termination, watchdogs, timeouts, migrations,
  Railway changes, environment-variable changes or deployment actions.
- [x] 4.2 Do not sync or archive this change; those remain user-controlled
  after review and validation.
