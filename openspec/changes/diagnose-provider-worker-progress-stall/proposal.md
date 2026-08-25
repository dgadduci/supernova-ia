# Proposal: diagnose provider-worker progress stalls

## Objective

Add decisive, privacy-safe measurements at the narrow boundaries that the
existing worker liveness trace does not distinguish: arming the inbound time
limit, entering and returning from the real inbound runner, and returning from
the per-cycle summary writer. This addresses the observed case where Uvicorn
continues accepting provider ingress while the worker stops starting new
cycles after a completed pass.

The change is diagnostic only. It does not repair a lease, restart a process,
alter the poll interval or timeout, or change requests, HTTPX, Ollama, the
proxy, T-C, Twilio or any business pipeline.

## Current execution path

The entrypoint starts Uvicorn and one provider-processing worker. In
`run_forever`, the worker emits `provider_worker_liveness` for cycle start,
inbound/outbound/sleep phase boundaries and cycle completion. `run_cycle`
calls `_run_inbound_with_timeout`, which installs the SIGALRM time limit and
then invokes `run_inbound_processing_main`; it writes the safe cycle summary
after the outbound pass. The next cycle follows the existing optional sleep.

Existing liveness can show that a phase was entered but cannot tell whether
the inbound timeout guard was armed before the actual runner was invoked, nor
whether the cycle summary writer returned. The separate active change
`diagnose-core-inbound-pre-llm-stall` begins only once the inbound coordinator
has been reached. This proposal observes the worker loop before that boundary
and must remain separate from it.

## Scope

- Extend the existing `provider_worker_liveness` event with two closed worker
  subphases: `inbound_runner` and `cycle_summary`.
- Emit start/completion/failure evidence around the real inbound runner only
  after the existing timeout timer is armed, and around the existing summary
  writer only after the normal runner sequence returns.
- Preserve the existing `inbound` phase as the outer bounded-pass boundary;
  it continues to describe the entire timeout-guarded pass.
- Document how to interpret incomplete liveness traces together with the
  existing worker cycle event and the separate core-inbound checkpoints.
- Add focused contract and ordering/failure tests, plus a bounded Railway log
  query documented as an operator aid.

## Non-goals

- No new worker, watchdog, heartbeat process, persistent diagnostic table,
  dashboard, alert, endpoint, background pipeline or automatic recovery.
- No modification to entrypoint supervision, lease/retry policies, signal
  semantics, poll interval, inbound timeout, transaction ownership, outbox or
  response delivery.
- No change to core inbound processing; that remains scoped to
  `diagnose-core-inbound-pre-llm-stall`.
- No raw messages, prompts, responses, model output, phone/provider/database
  identifiers, URLs, proxy values, credentials, exception messages or
  tracebacks in measurements.

## Diagnostic contract

`provider_worker_liveness` retains its closed existing outcomes and bounded,
process-local `cycle_index`. Its additional phases are:

- `inbound_runner`: start only after SIGALRM is installed and the timer is
  armed; completion only after `inbound_runner(bound)` returns; failure only
  when that call raises. It is nested inside the existing `inbound` phase.
- `cycle_summary`: start immediately before the existing
  `cycle_summary_writer(summary)` call; completion only after it returns;
  failure only when it raises. It occurs after outbound processing and before
  `cycle_completed`.

All emissions are best effort through the existing catalog. They add no calls
to a runner, writer, database or external service. A missing completion is
evidence only, never a synthetic timeout or outcome.

## Fallback behavior

Observability validation or serialization failure continues through the
existing fail-soft event path and cannot change the worker's work. A missing
or incomplete trace triggers neither fallback transport nor worker recovery.
Existing timeout and unexpected-exception propagation remain authoritative.

## Transaction ownership

The worker measurements do not receive a database session and SHALL NOT call
`commit`, `rollback`, `flush`, `refresh`, `begin` or `close`. The inbound CLI
and coordinator retain their existing transaction and lease ownership.

## Observability and interpretation

The operator correlates only the bounded `cycle_index` within one process
lifetime and timestamp ordering. Interpretation is deliberately narrow:

- `inbound` started without `inbound_runner` started: stop before/while arming
  the guard.
- `inbound_runner` started without completion/failure: the real inbound pass
  did not return; use the separate core checkpoints and LLM transport events
  only if they exist.
- `inbound` completed, outbound completed, but `cycle_summary` started has no
  terminal evidence: stop in the summary writer.
- `cycle_completed` followed by `sleep` started without completion: stop in
  the existing sleeper seam.
- completed sleep with no next `cycle_started`: stop in the outer-loop gap;
  this change does not claim a cause or recover it.

The events contain only phase/outcome, cycle index, bounded elapsed time and
closed exception metadata. They do not carry customer or provider correlation
because the worker-level seams can run when no item is due.

## Expected files

- `backend/cli/run_provider_processing_worker.py`
- `backend/observability/events.py`
- `backend/tests/test_provider_processing_worker.py`
- `backend/tests/test_production_observability.py`
- `backend/development/railway.md`
- This change's OpenSpec files

## Focused validation

The implementer must run and report the complete output from the user's local
terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py -q
PYTHONPATH=. venv/bin/ruff check backend/cli/run_provider_processing_worker.py backend/observability/events.py backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/cli/run_provider_processing_worker.py backend/observability/events.py
openspec validate diagnose-provider-worker-progress-stall --strict
git diff --check
```

No commit, push, PR, sync, archive, Railway configuration action or deploy is
part of this change.

## Rollback / reversibility

Removing the two phase tokens and their best-effort emission calls restores
the previous liveness surface. No migration, configuration value or durable
business state is introduced.

## Deferred limitations

A single stuck process cannot emit a new event after it stops executing. These
measurements identify its last observed boundary; they are not an independent
health monitor. Any stale-worker detection, restart policy or root-cause fix
requires a separate approved change based on the resulting trace.
