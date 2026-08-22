# Proposal: add Admin/Pilot Emulator timing observability

## Objective

Expose a bounded, correlated timing timeline for each Admin/Pilot Twilio
Emulator turn. The panel SHALL show a local browser timestamp beside the
operator message, each observed status, a received response and an error. It
SHALL also show the server-side timestamps for the worker's LLM request and
its completion or timeout so the operator can distinguish panel polling,
worker delay, LLM delay and outbound staging.

The display format SHALL be `HH:MM:SS.mmm`. Server timestamps SHALL remain
UTC ISO-8601 in the JSON contract and SHALL be formatted in the browser's
local timezone.

## Current execution path

The detail page submits to the existing
`POST /admin/pilot/orders/{pedido_id}/emulator-test` route and polls
`POST /admin/pilot/orders/{pedido_id}/emulator-test/status` using the returned
`synthetic_inbound_id`. The volatile conversation history currently renders
sent, status, response and error rows but has no timing metadata.

The status projection currently returns only `status`, `outbound_body` and
`provider_message_sid`. The deferred worker records receipt and processing
state timestamps, while the existing `llm_request` observability event emits
timestamps and elapsed duration without exposing a correlation timeline to
the Admin/Pilot panel.

## Scope

- Add bounded browser-observation timestamps beside every Emulator
  conversation kind: `Enviado`, `Estado`, `Respuesta recibida` and `Error`.
- Extend the existing status projection with a nullable, bounded `timeline`
  object scoped to the exact selected pedido/session/comercio and synthetic
  inbound identifier.
- Expose authoritative server timestamps for inbound receipt, LLM request,
  LLM completion/timeout, processing finalization and response staging when
  those timestamps are available.
- Persist only the minimum LLM timing metadata required to correlate the
  provider work item with the existing `llm_request` boundary. A nullable
  schema change is allowed; no prompt, LLM response body or customer payload
  may be persisted for this feature.
- Correlate provider-path LLM observability with the opaque synthetic inbound
  identifier through the existing safe correlation field, without logging
  message text, phone numbers, credentials or provider payloads.
- Preserve all existing status values, polling behavior, retry semantics,
  worker ownership, T-C routing and Twilio Emulator behavior.

## Non-goals

- No new worker, synchronous processing path, dispatcher or status source.
- No change to `accepted`, `processed`, `pending`, `sent`, `retryable` or
  `terminal` business meanings.
- No change to `LLM_TIMEOUT`, retry budgets, backoff, fallback responses or
  HTTP/TwiML behavior.
- No storage of prompts, LLM response text, customer message text, phone
  numbers, provider payloads, signatures, credentials or secrets.
- No history persistence in browser storage, cross-page history, export or
  download feature.
- No Railway, environment-variable, production or calibration changes.
- No OpenSpec sync/archive, commit, PR or deployment as part of implementation.

## Authoritative timing and fallback

The server-side timeline is authoritative for events produced by the
provider worker. The browser timestamp is authoritative only for when the
panel rendered or observed a row; it SHALL be labelled and SHALL NOT be
presented as a backend transition time.

The existing business outcomes remain authoritative. A missing or incomplete
timeline SHALL never trigger a retry, fallback, rejection, status change or
second LLM request. The panel SHALL render `—` for unavailable server times
and continue displaying the existing status/result.

## Shared boundary

```text
Existing Emulator submit/status polling
  -> exact synthetic_inbound_id projection
  -> persisted provider timing metadata + existing receipt/outbox timestamps
  -> bounded timeline JSON
  -> volatile browser conversation rows with local observed timestamps
```

## Transaction ownership

The existing provider coordinator/worker SHALL remain the owner of all
database writes and transaction boundaries. Timing fields SHALL be written
within the existing lease/finalization transaction. On a technical failure,
the timing captured before the rollback SHALL survive through the existing
retry or terminal finalization path without introducing an independent commit
or rollback.

## Observability

The existing `llm_request` events SHALL retain their timestamp and
`elapsed_ms`. Provider-path events MAY add the opaque synthetic inbound
correlation identifier through the existing safe field. Correlation values
and timeline fields SHALL be bounded and shall not contain PII, prompts,
responses, secrets, signatures or arbitrary exception text.

## Expected files

- `backend/models/procesamiento_mensaje_proveedor.py` — minimum nullable LLM
  timing/outcome fields if the existing model cannot represent them.
- `backend/alembic/versions/<new_revision>.py` — additive reversible migration
  only when required by the chosen persistence design.
- `backend/llm/query_llm.py` and the existing provider processing boundary —
  capture request/completion timestamps and safe correlation without changing
  LLM behavior.
- `backend/routers/admin_pilot_orders.py` — bounded timeline response scoped
  to the exact synthetic inbound target.
- `backend/templates/admin_pilot_orders/base.html` and, if needed,
  `backend/templates/admin_pilot_orders/detail.html` — render safe local
  timestamps and the server timeline.
- Focused tests for the model/migration, worker/LLM timing, status projection
  and Admin/Pilot rendering.

## Focused tests

- The panel renders `HH:MM:SS.mmm` beside sent, status, received and error
  rows and does not duplicate timestamps on repeated polling.
- The status endpoint returns only the timeline for the exact selected
  target and synthetic inbound identifier, with nullable fields before the
  worker reaches each milestone.
- A successful LLM call records request and completion timestamps and a
  timeout records completion/failure time and a closed timeout outcome while
  preserving existing retry behavior.
- The provider-path LLM event carries only safe correlation/timing metadata;
  no prompt, response body, PII or secret is emitted.
- Missing timeline data remains a non-blocking `—` in the panel and all
  existing Emulator status values and form contracts remain unchanged.

## Validation commands

The implementer must run and report complete output for:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_draft_inbound.py backend/tests/test_query_llm.py backend/tests/test_provider_processing_worker.py backend/tests/test_provider_message_receipt_core_integration.py -q
PYTHONPATH=. venv/bin/ruff check backend/models/procesamiento_mensaje_proveedor.py backend/llm/query_llm.py backend/services/provider_inbound_message_coordinator.py backend/routers/admin_pilot_orders.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_query_llm.py backend/tests/test_provider_processing_worker.py backend/tests/test_provider_message_receipt_core_integration.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/procesamiento_mensaje_proveedor.py backend/llm/query_llm.py backend/services/provider_inbound_message_coordinator.py backend/routers/admin_pilot_orders.py
openspec validate add-admin-pilot-emulator-timing-observability --strict
git diff --check
```

## Rollback and reversibility

The UI and response-contract changes are reversible by reverting the feature
commit. Any additive timing columns SHALL be nullable and removable through a
down migration or a subsequent controlled migration. Removing timing data
must not require changing receipts, outbox rows, worker leases or business
state.

## Deferred limitations

The first version does not provide a historical timeline after page reload,
does not expose full provider delivery-callback timing and does not display
LLM content. Provider acceptance time SHALL not be inferred from a browser
poll timestamp when the current outbox model has no authoritative transition
timestamp.
