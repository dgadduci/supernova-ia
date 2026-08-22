# Design: bound stuck provider turns and correct Emulator status

## Decision

Use the existing worker process as the recovery boundary. Apply one bounded
timeout around the existing inbound CLI pass in the worker process. On
timeout, propagate a dedicated safe timeout signal through the existing
worker failure path so the worker exits non-zero; `docker-entrypoint.sh`
already detects a dead worker sibling and terminates the web process, allowing
Railway's existing restart policy to recreate both processes.

Do not add a watchdog thread, a second worker, a queue, a new supervisor or a
coordinator-side timeout. The timeout must not own or repair the coordinator's
transaction. The existing processing lease expires and is reclaimed by the
existing repository rules after restart.

## Timeout contract

The worker setting is a positive integer in seconds. Its default must be
derived from the configured model/embedding timeouts so the default is not
shorter than a valid configured model operation; an explicit environment
override is allowed and is validated at worker startup. The implementation
must document the effective bound in safe configuration metadata without
printing the raw environment value in an error or event.

The timeout is installed only for the production worker's inbound-pass seam
and is always restored in a `finally` block. The timeout exception is a safe
class-only signal and must cross the existing inbound CLI's ordinary
`Exception` handling so that the worker supervisor, rather than the business
pass, owns process restart. A normal return removes the timer and preserves
the existing result and cycle order.

When the timeout fires:

```text
provider_worker_liveness phase_started(inbound)
  -> provider_worker_liveness phase_failed(inbound, safe timeout type)
  -> worker exits non-zero
  -> existing entrypoint detects provider_worker_exited
  -> existing Railway restart policy recreates the service
  -> existing lease-expiry/reclaim path makes the row eligible
```

No `phase_completed`, `provider_inbound_processing_outcome`, fallback
response, outbound pass, lease finalization or dispatcher call is fabricated
by this path.

## Status projection contract

Keep `_emulator_outbox_summary` as the only status projection boundary. When
receipt-linked outbox rows exist, preserve the current outbox-state mapping.
When no outbox rows exist, derive the HTTP status from the already-built
closed `EmulatorDiagnostic` rather than using a constant `processed` value.

The projection remains exact and read-only:

| Diagnostic state | Wire status | Polling behavior |
| --- | --- | --- |
| `not_started`, `pending`, `leased`, `unknown` | `pending` | continue polling |
| `processed_without_response` | `processed` | finish neutrally |
| `retryable` | `retryable` | finish with bounded state |
| `terminal` | `terminal` | finish with bounded state |

The missing-receipt branch remains `accepted`. The route never treats a
missing processing row as success and never reads a different target to fill
the projection.

## Failure handling and transaction semantics

The timeout handler is fail-safe and process-scoped. It does not call any
SQLAlchemy transaction method or repository finalizer. The normal Python
process/session cleanup and the existing durable lease expiry are the only
recovery mechanisms. If the timeout occurs while a database call is blocked,
process termination releases the connection at the operating-system/runtime
boundary; no in-process repair is attempted.

The status route remains read-only and continues to return a bounded response
with no message body, SID, provider payload, prompt, exception text or
credential.

## Rejected alternatives

- A coordinator-side finalization on timeout was rejected because the timeout
  does not prove whether the transaction or external dependency completed.
- A watchdog thread or a second worker was rejected because it would add
  concurrency and create duplicate-claim/recovery races.
- A fixed database `statement_timeout` was rejected for this change because
  the current engine is shared by web and worker sessions and would alter
  unrelated request behavior.
- Treating zero outbox rows as `processed` was rejected because it hides
  pending/leased work and caused the observed panel misdiagnosis.

## Focused test seams

Use the existing injectable worker runners and summary/event seams. Add only
the smallest timeout seam needed to test a runner that exceeds the bound
without sleeping for a production-sized interval. Assert that the timer is
restored, the outbound runner is not called after timeout, and the existing
supervisor exception path receives only the safe timeout type.

Use existing exact-target router fixtures and the existing JSDOM/browser
contract tests to cover every no-outbox mapping and ensure pending polling
does not append an Emulator rejection.
