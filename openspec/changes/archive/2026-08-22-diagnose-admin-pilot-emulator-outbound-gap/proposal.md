# Proposal: diagnose Admin/Pilot Emulator outbound gap

## Objective

Make the observed Admin/Pilot Twilio Emulator failure diagnosable at the
boundary between deferred inbound processing and outbound staging. The system
must distinguish these facts without inference:

- the synthetic inbound was accepted;
- the provider worker finished processing;
- the pipeline produced zero or more customer responses;
- zero or more durable outbound rows were staged; and
- an outbound dispatcher/T-C attempt actually occurred.

The panel must stop presenting a polling timeout after a `processed` turn with
no outbound row as “El Twilio Emulator rechazó el mensaje”. That text is not
supported by the current evidence: the emulator accepted the inbound, while
no outbound `Messages.json` request was made.

This is an investigation and diagnostic change. It must not invent a response,
retry the inbound, bypass the worker, or change the LLM/pipeline decision.

## Current execution path

The Admin/Pilot detail page submits a bounded message to
`POST /admin/pilot/orders/{pedido_id}/emulator-test`. The route asks the
standalone Twilio Emulator to inject a signed inbound through the T-C webhook
and returns a synthetic inbound identifier. The browser polls
`POST /admin/pilot/orders/{pedido_id}/emulator-test/status`.

The T-C webhook and NovaOrders isolated ingress accept the inbound and create
the provider receipt plus deferred processing work item. The provider worker
leases that item, runs the existing transactional message pipeline, calls
`stage_outbound_rows`, finalizes the processing row and later lets the bounded
outbound dispatcher call the T-C outbound route. The T-C then calls the
standalone emulator Messages API.

The current status projection maps a completed processing row with no outbox
row to `status=processed` and no body. The browser continues polling until
its limit and then uses the generic emulator-rejected message. The current
projection does not expose whether the pipeline produced zero responses or
whether outbound staging/dispatch was reached.

## Scope

- Add a closed, privacy-safe structured processing outcome for the provider
  worker at the existing coordinator boundary. It must expose bounded
  response/outbox counts and the existing opaque provider correlation only
  where the current timing contract permits it.
- Extend the exact synthetic-inbound status projection with a bounded
  diagnostic state and counts. The projection must remain scoped to the
  selected pedido/session/comercio and exact synthetic inbound identifier.
- Treat `processed` with zero staged outbound rows as a definitive
  `processed_without_response` diagnostic state, without changing the
  existing business status or creating a fallback response.
- Update the Admin/Pilot browser to stop polling on that definitive state and
  show a precise diagnostic message. Polling/transport failures must not be
  labelled as a Twilio Emulator rejection.
- Add focused tests covering the zero-response path, response/outbox counts,
  exact-target isolation, structured-event privacy, and browser terminal
  handling.
- Preserve the existing LLM timing timeline; use it as supporting evidence,
  not as a new LLM decision or retry mechanism.

## Non-goals

- No change to LLM prompts, model, timeout, classifier, recognizer or business
  intent selection.
- No automatic generic response, retry, replay, second LLM call, new outbox
  row or alternate channel when the pipeline produces no response.
- No change to worker cadence, lease duration, transaction ownership, retry
  policy, outbound state machine, T-C HTTP contract, Twilio Emulator behavior,
  HTTP status codes or TwiML.
- No database migration unless the implementation proves that the existing
  receipt, processing and outbox rows cannot represent the required bounded
  projection. Prefer deriving the diagnostic from existing durable rows and
  the returned mapper count.
- No change to Railway, environment variables, secrets, commerce state,
  production or calibration.
- No dashboard, alerting backend, tracing service or general logging-format
  migration.
- No raw message body, phone number, provider payload/SID, prompt, model
  output, URL, credential, token, exception message or traceback in the new
  event or status response.
- No OpenSpec sync/archive, commit, push, PR or deployment as part of
  implementation.

## Shared boundary

```text
Admin/Pilot submit
  -> emulator inbound acceptance
  -> T-C / NovaOrders receipt acceptance
  -> provider worker process_lease
  -> existing process_incoming_message
  -> stage_outbound_rows (response_count/outbox_count)
  -> processing finalization
  -> exact status projection
  -> browser terminal diagnostic

Existing outbound dispatcher -> T-C -> emulator Messages API remains unchanged.
```

The new evidence observes the coordinator result and the existing durable
receipt/processing/outbox rows. It does not decide business outcomes, own a
transaction, call the dispatcher or contact T-C.

## Authoritative outcomes and fallback behavior

- The existing coordinator and processing-row state remain authoritative for
  business processing: `processed`, `retryable` and `failed_terminal` retain
  their current meanings.
- `processed_with_response` is diagnostic evidence that one or more customer
  responses were rendered and one or more outbound rows were staged.
- `processed_without_response` is diagnostic evidence that processing
  finalized as `processed` and zero outbound rows were staged. It is not a
  Twilio or T-C rejection and must not trigger a retry or fallback response.
- A `retryable`, `terminal` or lease-loss result remains governed by the
  existing worker/dispatcher state machine. The panel may display the bounded
  state but must not initiate recovery.
- If the diagnostic event cannot be validated or serialized, the existing
  business path continues unchanged.
- If diagnostic data is absent or malformed, the status endpoint preserves the
  existing status projection and the browser displays a neutral status-query
  failure, never a fabricated provider rejection.

## Transaction ownership

The coordinator remains the sole owner of the deferred processing transaction.
Response/outbox counts are captured from the existing mapper result inside
that transaction. Processing and outbound rows are finalized exactly as they
are today. Structured-event emission is best effort and must not create a
second commit, rollback, lease transition or retry.

The Admin/Pilot status route remains read-only. It may query the exact receipt,
processing row and outbox rows, but it must not flush, commit, process work,
send to a provider or repair missing output.

## Observability

Add one versioned event, `provider_inbound_processing_outcome`, using the
existing safe event sink and the `provider_worker` component. Its closed
outcome vocabulary is:

- `processed_with_response`;
- `processed_without_response`;
- `retry_scheduled`;
- `failed_terminal`;
- `lease_lost`; and
- `unavailable`.

The event may contain only bounded `response_count`, `outbox_row_count`,
`failure_category` and the existing safe opaque `correlation_id` when
available. It must not contain IDs, bodies, addresses, provider payloads,
exception text or arbitrary reason strings. The event is emitted after the
authoritative processing result is known; it is not a substitute for the
existing `outbound_attempt_outcome` event.

## Expected files

- `backend/observability/events.py` — new event catalogue, closed outcomes,
  safe fields and validation.
- `backend/observability/__init__.py` — export the new event constant only if
  required by the repository convention.
- `backend/services/provider_inbound_message_coordinator.py` — capture the
  existing mapper result count and emit the outcome after the current durable
  result, without changing transaction or retry ownership.
- `backend/routers/admin_pilot_orders.py` — add the closed diagnostic model and
  exact-target projection using existing durable rows.
- `backend/templates/admin_pilot_orders/base.html` — stop polling on
  `processed_without_response` and render neutral diagnostic text.
- Focused tests under `backend/tests/` for the event, coordinator,
  Admin/Pilot status projection and browser behavior.
- `openspec/specs/provider-emulator-outbound-diagnostics/spec.md` after sync.

Do not modify `commerce_adapter/` or `twilio_emulator/` unless a focused test
proves a contract regression in those services. The current incident evidence
shows both accepted inbound requests and no outbound request reaching the
emulator, so the first implementation boundary is NovaOrders processing and
the Admin/Pilot projection.

## Focused tests

- The event accepts only the closed outcomes and bounded count/correlation
  fields and rejects bodies, phone values, provider identifiers, raw error
  text and unknown fields.
- A coordinator turn with a non-empty mapper result emits
  `processed_with_response` with matching bounded counts.
- A coordinator turn that finalizes `processed` with zero staged rows emits
  `processed_without_response` and does not create a fallback row or invoke
  the outbound dispatcher.
- Retryable, terminal, unavailable and lease-loss paths preserve existing
  finalization and emit their corresponding diagnostic outcome.
- The status projection returns diagnostic data only for the exact selected
  target and synthetic inbound identifier; a missing target cannot leak data
  from another receipt/order.
- The browser stops polling on `processed_without_response`, displays a
  neutral “procesado sin respuesta outbound” diagnostic and does not append
  “El Twilio Emulator rechazó el mensaje.”
- Polling HTTP errors, malformed status payloads and exhausted polling use a
  neutral status-query error while actual terminal outbound states retain
  their existing bounded state display.
- Existing successful emulator turns still render the response and preserve
  the timing timeline and conversation history.

## Validation commands

The implementer must run and report complete output for:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_provider_processing_worker.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_draft_inbound.py backend/tests/test_production_observability.py -q
PYTHONPATH=. venv/bin/ruff check backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/routers/admin_pilot_orders.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_provider_processing_worker.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_draft_inbound.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/routers/admin_pilot_orders.py
openspec validate diagnose-admin-pilot-emulator-outbound-gap --strict
git diff --check
```

The repository instructions require the environment-dependent commands to be
run in the user's local terminal and their complete output reviewed before
implementation approval.

## Rollback and reversibility

Rollback is a code-only revert of the event, projection and browser diagnostic
changes. It does not alter receipts, processing rows, outbox rows, leases,
messages, provider configuration or commerce state. No migration is expected;
if one is proven necessary, it must be additive, nullable and reversible.

## Deferred limitations

This change identifies and displays the point where an inbound turn stops
producing outbound work; it does not decide why the existing pipeline returned
zero responses. Once the evidence shows whether the cause is empty intents,
response mapping, transaction rollback, worker interruption or another bounded
failure, a separate approved change may correct that business path. No such
correction is included here.
