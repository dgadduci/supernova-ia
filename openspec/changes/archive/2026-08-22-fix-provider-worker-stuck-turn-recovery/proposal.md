# Proposal: bound stuck provider turns and correct Emulator status

## Objective

Prevent one live-but-blocked provider turn from stopping all later turns, and
stop the Admin/Pilot Emulator from reporting `processed` when the exact turn
has no durable processing completion.

The incident that motivates this change is bounded by production evidence:
the first test turn reached the LLM and outbound delivery, the second turn
emitted `provider_inbound_stage=availability, outcome=started` without a
matching completion, and the single worker produced no later cycles until the
service was restarted. The status panel nevertheless showed `processed`
because the status projection currently treats zero outbox rows as processed.

## Current execution path

`docker-entrypoint.sh` starts Uvicorn and the provider worker as sibling
processes. The worker runs a synchronous `run_forever` loop, invokes the
bounded inbound CLI, then the bounded outbound CLI, and sleeps. The inbound
CLI claims one durable processing row and calls
`ProviderInboundMessageCoordinator.process_lease`.

The coordinator's availability stage calls
`CommerceAvailabilityService.evaluate`, which uses the existing SQLAlchemy
session to read the exact commerce and operation state. The worker liveness
and provider-inbound-stage events already expose a stage start, but the
current worker has no upper bound that causes the worker process to exit when
the inbound pass never returns.

The Admin/Pilot status route reads the exact receipt, processing row and
receipt-linked outbox rows. Its current zero-outbox branch returns
`status=processed` without consulting the durable processing state.

## Scope

- Add one positive worker setting,
  `PROVIDER_PROCESSING_WORKER_INBOUND_TIMEOUT_SECONDS`, with a safe default
  derived from the configured model timeouts and an explicit operator
  override.
- Bound the existing inbound pass at the worker-process boundary. A timeout
  emits only safe worker-liveness failure evidence, lets the existing process
  supervisor restart the service, and leaves durable lease recovery to the
  existing coordinator/repository contract.
- Preserve the existing inbound-before-outbound order. A timed-out inbound
  pass MUST NOT invoke the outbound pass in that worker process.
- Make the Emulator status projection derive its HTTP status from the exact
  diagnostic state when no outbox row exists. Pending, leased, not-started
  and unknown states must never be reported as `processed`.
- Add focused tests for timeout propagation/supervision semantics, settings
  validation, exact status mapping and browser polling behavior.

## Non-goals

- No LLM, prompt, classifier, semantic recognizer, T-C, Twilio Emulator or
  outbound-dispatch behavior changes.
- No new queue, worker, thread, scheduler, migration, database table or
  parallel processing pipeline.
- No manual lease repair, forced durable finalization, fallback response,
  replay or automatic outbound retry caused by the timeout.
- No change to HTTP/TwiML contracts, provider credentials, commerce state,
  Railway variables or deployment configuration in this change.
- No raw message text, phone numbers, provider IDs, URLs, credentials,
  exception messages or tracebacks in timeout evidence or status payloads.

## Shared boundary

The worker timeout belongs at the existing inbound-pass boundary, outside the
coordinator's transaction and outside the outbound dispatcher. Recovery is
provided by the existing `docker-entrypoint.sh` process supervision and the
existing durable processing lease expiry/reclaim path.

The status correction belongs in `_emulator_outbox_summary` and its existing
browser polling contract. It remains a read-only projection of the exact
selected receipt, processing row and outbox rows.

## Authoritative outcomes and fallback behavior

- A normal inbound return keeps the existing coordinator result and the
  existing inbound-then-outbound worker cycle.
- If the bounded inbound pass exceeds its configured timeout, the worker
  records a safe `provider_worker_liveness` inbound phase failure and exits
  non-zero through the existing supervisor path. It MUST NOT fabricate a
  processing outcome, call outbound, repair the lease or create a response.
- After process restart, the existing lease-expiry/reclaim rules remain the
  only authority for making the interrupted work eligible again.
- With no outbox rows, the status route maps the exact durable diagnostic as:
  `not_started`, `pending`, `leased` and `unknown` -> HTTP status
  `pending`; `retryable` -> `retryable`; `terminal` -> `terminal`;
  `processed_without_response` -> `processed`. The existing `accepted`
  response for a receipt that does not yet exist remains unchanged.
- The browser continues polling for `pending`; terminal retryable/terminal
  states remain visible; a bounded polling exhaustion remains neutral and
  MUST NOT be described as an Emulator rejection.

## Transaction ownership

The change owns no transaction. The coordinator continues to own claim,
processing, rollback and finalization. The worker timeout handler must not
call `commit`, `rollback`, `flush`, `close`, lease finalization or a second
database connection; normal process/session cleanup and durable lease
recovery remain authoritative.

## Observability

Reuse the existing `provider_worker_liveness` event with the existing closed
`phase_failed`/`inbound` vocabulary and a safe exception type such as the
bounded timeout type. Do not add free-form diagnostic fields. A timeout is
operational evidence, not a durable business outcome.

## Expected files

- `backend/config/settings.py` — timeout setting, default and validation.
- `backend/cli/run_provider_processing_worker.py` — bounded inbound-pass
  enforcement and safe timeout propagation through the existing supervisor.
- `backend/routers/admin_pilot_orders.py` — exact no-outbox status mapping.
- `backend/templates/admin_pilot_orders/base.html` — only if needed to keep
  pending/terminal polling behavior aligned with the corrected wire status.
- `backend/tests/test_provider_processing_worker.py` — timeout and
  supervision tests.
- `backend/tests/test_admin_pilot_orders_panel.py` — exact projection and
  browser contract tests.
- `openspec/specs/provider-worker-stuck-turn-recovery/spec.md` and
  `openspec/specs/admin-pilot-emulator-status-integrity/spec.md` after sync.

## Focused tests

- Positive/default/invalid timeout settings fail closed when the worker is
  enabled and do not expose the configured value in logs.
- An inbound pass that returns before the bound preserves inbound-before-
  outbound ordering and invokes outbound exactly once.
- An inbound pass that exceeds the bound raises the safe timeout through the
  worker supervisor path, emits no fabricated completion/business outcome,
  and does not invoke outbound.
- Existing lease-expiry/reclaim ownership is not called directly by the
  timeout path.
- Exact no-outbox diagnostics map to `pending`, `retryable`, `terminal` or
  `processed` as specified; pending data from another target cannot enter
  the projection.
- Browser polling keeps pending turns pending, stops on definitive
  processed-without-response, and uses the existing neutral timeout message.

## Validation commands

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_processing_worker.py backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/ruff check backend/config/settings.py backend/cli/run_provider_processing_worker.py backend/routers/admin_pilot_orders.py backend/templates/admin_pilot_orders/base.html backend/tests/test_provider_processing_worker.py backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/cli/run_provider_processing_worker.py backend/routers/admin_pilot_orders.py
openspec validate fix-provider-worker-stuck-turn-recovery --strict
git diff --check
```

## Rollback and reversibility

Rollback is a code-only revert of the timeout and projection changes. It does
not alter durable rows, leases, migrations, commerce configuration,
provider credentials or deployment state. The existing manual service
restart procedure remains available if the timeout is disabled or reverted.

## Deferred limitations

This change bounds the worker and corrects the panel's state projection; it
does not identify or repair the underlying database/network reason that made
the availability read stop returning. A separate investigation remains
appropriate if the bounded failure recurs after recovery is deployed.
