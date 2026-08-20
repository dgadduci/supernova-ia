# Design: provider worker liveness observability

## Design decision

Instrument the existing synchronous worker at its orchestration boundary and
extend the existing privacy-safe event catalogue. Do not add a watchdog thread,
signal timeout or second process. A missing completion event is useful evidence
without imposing a new failure mode on a valid long-running operation.

## Event contract

Add `provider_worker_liveness` with component `provider_worker`.

The event contract has the following closed values:

| Field | Values / bounds | Meaning |
| --- | --- | --- |
| `outcome` | `cycle_started`, `phase_started`, `phase_completed`, `phase_failed`, `cycle_completed` | Lifecycle observation, not a business result |
| `phase` | `readiness`, `inbound`, `outbound`, `sleep` | The worker phase being observed; absent for cycle outcomes |
| `cycle_index` | Positive bounded integer | Process-local cycle number; never a correlation or customer identifier |
| `elapsed_ms` | Existing non-negative bounded duration | Duration of a completed/failed phase or cycle |
| `failure_category` | `worker_exception` only when applicable | Safe technical category, never an exception message |
| `exception_type` | Existing safe exception-class validator | Class name only, never `str(exc)` or traceback |

`phase_started` requires `phase` and `cycle_index`. `phase_completed` and
`phase_failed` require the same fields and may include `elapsed_ms`.
`cycle_started` and `cycle_completed` require `cycle_index`; cycle completion
may include `elapsed_ms`. A liveness event never includes `outbox_id`,
`correlation_id`, provider metadata or arbitrary free-form fields.

## Instrumentation sequence

The worker preserves its current control flow:

```text
cycle_started
  -> phase_started(readiness) [only while readiness is not cached]
  -> phase_completed(readiness)
  -> phase_started(inbound) -> existing bounded inbound CLI
  -> phase_completed(inbound)
  -> phase_started(outbound) -> existing bounded outbound CLI
  -> phase_completed(outbound)
  -> existing safe cycle summary
  -> phase_started(sleep) -> existing configured sleep
  -> phase_completed(sleep)
  -> next cycle
```

When the readiness probe reports not-ready, readiness still completes with
the existing safe readiness event, inbound remains skipped, and outbound is
instrumented as usual. When a runner or sleeper raises, the corresponding
phase emits `phase_failed` with safe type/category metadata and the existing
exception path re-raises. No completion event is fabricated after a failure.

`cycle_completed` is emitted only after the existing `run_cycle` summary
writer returns successfully. If the worker never returns from a phase, the
last `phase_started` event is the intentional evidence boundary.

## Timing and failure handling

Use the existing monotonic clock seam or an injectable clock in focused tests;
do not use customer/provider timestamps or wall-clock values as state. Phase
duration is emitted only after return or exception. The instrumentation must
not catch business outcomes, convert exit codes, release leases, or make a
retry decision.

The shared `emit_event` contract remains best-effort and privacy-safe. An
observability emission failure uses the existing failure event and must not
interrupt the worker's existing business path.

## Boundaries preserved

- `run_inbound_processing_main` remains the only inbound pass called by the
  worker.
- `run_outbound_dispatch_main` remains the only outbound pass called by the
  worker.
- Inbound and outbound ordering remains strictly inbound before outbound.
- `ProviderInboundMessageCoordinator` and `OutboundMessageDispatcher` retain
  all claim, transaction, lease, retry, idempotency and finalization ownership.
- `docker-entrypoint.sh` remains the existing process supervisor; this change
  does not change deployment or restart policy.

## Test seams

The current injectable runner, sleeper, readiness probe, stop predicate and
summary writer seams remain. Add an event sink or clock seam only where needed
to assert ordered safe events; production defaults continue using the shared
event emitter and monotonic clock.

Tests must prove absence as well as presence: no `phase_completed` is written
when a bounded runner raises, no liveness event carries a forbidden field, and
the worker does not call outbound before inbound has returned.

## Rejected alternatives

- A fixed timeout around inbound/outbound was rejected because current LLM and
  provider operations can legitimately be slow, and killing an ambiguous
  provider call could create a duplicate-delivery risk.
- A watchdog thread or second Railway process was rejected because it would
  add concurrency and recovery semantics before the stalled phase is known.
- A new queue or database heartbeat row was rejected because the existing
  durable receipt/outbox leases already provide recovery state and the problem
  is missing phase evidence at the worker boundary.
