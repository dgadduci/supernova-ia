# Proposal: add provider worker liveness observability

## Objective

Make a live-but-not-progressing provider-processing worker diagnosable without
changing inbound processing, outbound delivery, lease recovery, retry policy or
HTTP behavior. Operators must be able to identify the last worker phase that
started, whether it completed, and whether the worker resumed after an
unexpected technical failure.

This is the smallest safe correction for the 2026-08-20 pilot incident. The
worker service remained healthy at the process/service level, but a pending
message was not processed until `supernova-ia` was restarted. The evidence
proves restart recovery, not whether the preceding condition was a long
inbound call, a long outbound call, a blocked dependency or a stalled loop.

## Current execution path

`docker-entrypoint.sh` starts `uvicorn` and, when
`PROVIDER_PROCESSING_WORKER_ENABLED` is enabled, starts
`python -m backend.cli.run_provider_processing_worker` as a sibling process.
The entrypoint checks only whether the worker PID is alive. The worker runs a
readiness probe when needed, then calls the existing bounded inbound CLI, the
existing bounded outbound CLI and the configured sleep in a synchronous loop.
The worker emits its structured cycle evidence only after the inbound and
outbound phases have returned.

The inbound CLI owns the inbound claim/process/finalization path. The outbound
CLI and dispatcher own the outbox claim, provider call and conditional
finalization path. Their leases and retry state are already durable recovery
boundaries.

## Scope

- Add one versioned `provider_worker_liveness` event to the existing safe
  observability catalogue.
- Emit bounded phase evidence for cycle start/completion and readiness,
  inbound, outbound and sleep phase start/completion/failure.
- Include only a closed phase token, a bounded cycle index, a bounded elapsed
  duration and safe exception type/category metadata when a phase fails.
- Preserve the existing cycle event, worker ordering, configured cadence,
  bounded pass limits and supervisor behavior.
- Add focused tests proving phase ordering, incomplete-phase diagnosis,
  technical-failure evidence and privacy safety.

## Non-goals

- No automatic watchdog, forced process termination or blind phase timeout in
  this change. A valid LLM/provider operation may be long-running, and killing
  it without a proven bound could cause an ambiguous outbound result or a
  duplicate attempt.
- No change to the Railway service, deployment, environment variables,
  secrets, commerce activation or manual restart procedure.
- No database schema, migration, queue, scheduler, second worker, parallel
  pipeline or new transaction boundary.
- No change to Twilio HTTP/TwiML responses, inbound recognition, outbound
  wording, provider idempotency, lease duration, retry bounds or ordering.
- No raw message, phone number, provider SID/payload, prompt, model output,
  URL, credential, token, exception message or traceback in liveness evidence.

## Shared boundary

The boundary is the existing worker orchestration seam around the readiness
probe and the two bounded CLI passes. The liveness emitter observes phase
entry, return and exception state; it does not claim work, select business
outcomes, send to a provider, own a transaction or decide whether a row is
retryable.

## Authoritative outcomes and fallback behavior

- Existing inbound and outbound CLI results remain the authoritative business
  outcomes: processed, retryable, terminal, sent, no-due and their existing
  technical exit behavior.
- A completed liveness phase is observational evidence only. It must not be
  interpreted as successful business processing.
- An exception escaping a phase is a technical worker failure. The liveness
  event records only the closed phase and exception class/category, then the
  existing worker failure path re-raises so the current entrypoint supervisor
  can restart the service.
- A phase with a `phase_started` event and no matching completion is the
  authoritative operational signal for a possible long-running or stalled
  phase. The worker must not invent a retry, release a lease, skip a phase or
  terminate itself based only on missing evidence.
- If liveness-event validation or serialization fails, the existing
  privacy-safe observability failure handling applies and the business path
  continues unchanged.

## Transaction ownership

This change owns no transaction. The inbound coordinator continues to own
inbound claim and processing transactions. The outbound dispatcher continues
to own outbox leases, provider calls and conditional finalization. The worker
only calls the existing bounded CLI seams.

## Observability

`provider_worker_liveness` is emitted as a single JSON line through the shared
event sink. The event uses the `provider_worker` component and a closed
vocabulary:

- outcomes: `cycle_started`, `phase_started`, `phase_completed`,
  `phase_failed`, `cycle_completed`;
- phases: `readiness`, `inbound`, `outbound`, `sleep`;
- safe optional fields: `cycle_index`, `phase`, `elapsed_ms`,
  `failure_category` and `exception_type` according to the event contract.

The event contains no customer/provider identifier or payload. The existing
`provider_worker_cycle` event remains the summary source for bounded pass
outcomes and is not replaced by the phase event.

## Expected files

- `backend/observability/events.py` — event catalogue, closed phase/outcome
  validation and safe optional fields.
- `backend/cli/run_provider_processing_worker.py` — phase instrumentation
  around the existing seams without changing their order or ownership.
- `backend/tests/test_provider_processing_worker.py` — phase ordering,
  incomplete-phase and exception-path tests.
- `backend/tests/test_production_observability.py` — event build/parse and
  privacy-contract tests.
- `openspec/specs/provider-worker-liveness-observability/spec.md` after sync.

## Focused tests

- The liveness event accepts only the catalogued outcomes, phases and bounded
  numeric fields.
- A normal ready cycle emits cycle start, readiness, inbound, outbound,
  sleep and cycle completion evidence in order while preserving inbound before
  outbound.
- A not-ready cycle records readiness evidence, skips inbound according to the
  existing contract, and still records outbound evidence.
- An inbound or outbound exception records `phase_failed` with safe typed
  metadata and preserves the existing re-raise/supervisor behavior.
- A runner that does not return leaves a `phase_started` record without a
  fabricated completion or recovery outcome; the test uses a bounded seam and
  does not sleep or call a provider.
- The serialized event contains no sensitive or customer/provider payload and
  round-trips through the existing production-log parser.

## Validation commands

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py -q
PYTHONPATH=. venv/bin/ruff check backend/observability/events.py backend/cli/run_provider_processing_worker.py backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability/events.py backend/cli/run_provider_processing_worker.py
openspec validate add-provider-worker-liveness-observability --strict
git diff --check
```

The repository instructions require these environment-dependent validations
to be run by the user in the local terminal and their complete output reviewed
before implementation approval.

## Rollback and reversibility

Rollback is a code-only revert of the event catalogue and worker instrumentation.
It does not touch durable work rows, leases, retries, migrations, provider
configuration or commerce state. Existing cycle summaries and the manual
restart procedure remain available during rollback.

## Deferred limitations

This change identifies the last phase that began but does not automatically
decide that a phase is stalled. After phase evidence identifies the actual
failure mode and a safe upper bound is established, a separate approved change
may add bounded recovery or a platform-level alert. Automatic termination is
deliberately deferred until it can be proven not to interrupt valid LLM or
provider operations.
