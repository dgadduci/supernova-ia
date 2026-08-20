# Proposal: add admin pilot Twilio emulator

## Objective

Allow the authenticated admin/pilot console to submit a controlled test
message that traverses the same commerce-owned T-C inbound, NovaOrders
ingress, worker, outbox and T-C outbound boundaries as a real WhatsApp
message, without calling the real Twilio API or incurring provider cost.

The change introduces a test-only `twilio-emulator` with two provider
surfaces:

- a Twilio-shaped inbound driver that signs and forwards a form webhook to
  the configured T-C webhook;
- a Twilio-shaped Messages API that accepts the T-C outbound request,
  captures the bounded test delivery and returns a generated fake
  `MessageSid`.

The emulator uses generated Twilio-shaped test credentials only inside the
test configuration. Those values are never sent to the real Twilio service,
never displayed in the admin browser and never logged.

## Current execution path

The existing admin/pilot `POST /admin/pilot/orders/{pedido_id}/local-test`
route is intentionally local-only. It invokes the response orchestrator
directly and does not create a provider receipt, outbox row, worker lease or
Twilio request. It must remain unchanged so the existing local diagnostic
channel keeps its current meaning.

The real isolated provider path is:

```text
Twilio webhook
  -> T-C adapter
  -> authenticated NovaOrders ingress
  -> provider coordinator and deferred work
  -> provider-processing worker
  -> existing outbox dispatcher
  -> authenticated T-C outbound command
  -> T-C Twilio client
  -> real Twilio Messages API
```

The new admin/pilot path will replace only the real provider at the outer
boundary:

```text
Admin/pilot emulator action
  -> twilio-emulator signed inbound driver
  -> existing T-C webhook
  -> existing NovaOrders ingress/coordinator
  -> existing worker/outbox/dispatcher
  -> existing T-C outbound command
  -> twilio-emulator Messages API
```

The worker remains asynchronous and is not invoked directly by the admin
route.

## Scope

- Add a standalone `twilio_emulator/` service/package with:
  - generated Twilio-shaped test account SID and auth token configuration;
  - an authenticated control endpoint for one bounded inbound test;
  - Twilio-compatible signature generation for the complete submitted form;
  - a configured T-C webhook target, with no arbitrary target URL accepted;
  - a Twilio-compatible outbound Messages API surface using HTTP Basic
    authentication with the generated test credentials;
  - deterministic, unique fake `MessageSid` values and bounded in-memory
    capture with explicit retention limits;
  - health and test-only inspection surfaces protected by a control token.
- Add an explicit T-C provider mode (`real` or `emulator`) with `real` as
  the default. Emulator mode SHALL never instantiate or call the real Twilio
  SDK.
- Add the equivalent opt-in emulator transport seam to the central outbound
  Twilio adapter so controlled provider tests cannot accidentally call real
  Twilio when the emulator mode is enabled. The existing real mode and the
  isolated routing fallback remain unchanged.
- Add an explicit admin/pilot action labelled as a Twilio-emulator test. It
  SHALL be separate from the existing local-only chat action and SHALL:
  - require the existing admin authentication and same-origin protection;
  - validate the exact selected active Session, Pedido, Cliente, Comercio and
    dedicated channel identity;
  - reject unavailable commerces, missing/inactive installations and any
    missing emulator configuration without falling back to real Twilio or
    the central path;
  - ask the emulator to deliver the test inbound through the configured T-C
    webhook using the selected client and channel addresses;
  - return a bounded test identifier and allow the browser to poll the exact
    provider receipt/outbox state until the simulated outbound is captured;
  - display the simulated outbound body and typed delivery state only in the
    authenticated test console.
- Add safe observability for emulator inbound control, emulator outbound
  acceptance and admin test rejection. Events SHALL contain no message body,
  phone number, credential, signature, URL, raw exception or arbitrary input.
- Add focused tests for the emulator, both provider modes, admin isolation,
  signature correctness, exact T-C routing, asynchronous status polling and
  the no-real-Twilio invariant.

## Non-goals

- Do not change the existing admin/pilot local-only route or silently change
  its meaning.
- Do not send generated credentials to Twilio or attempt to make fake
  credentials valid against the real provider.
- Do not add a second business-processing pipeline, a second worker, a queue,
  a scheduler or a new transaction boundary.
- Do not make emulator mode the default or enable it in production.
- Do not change the real T-C webhook contract, NovaOrders ingress contract,
  worker ordering, outbox leases, retries or durable idempotency rules.
- Do not fall back from a failed emulator test to real Twilio, central Twilio
  or the local direct processor.
- Do not add a database migration for emulator captures. The existing
  provider receipt/outbox remains the source of truth for the admin status
  projection.
- Do not expose provider credentials, raw provider payloads or unbounded
  test history through the browser.

## Shared boundary

The shared boundary is the existing T-C provider boundary. The emulator
implements provider transport behavior only; it does not own commerce
selection, customer identity, business processing, the provider receipt,
the outbox or worker execution.

The admin action is a test driver, not a new business entry point. It must
submit a provider-shaped event to the emulator and let the existing T-C and
NovaOrders path decide acceptance, duplication, rejection and outbound work.

## Authoritative outcomes and fallback behavior

- The existing T-C/NovaOrders coordinator outcome remains authoritative for
  inbound acceptance, duplicate and business rejection.
- The existing outbox dispatcher outcome remains authoritative for outbound
  `sent`, `retryable` and `terminal` state.
- The emulator's fake `MessageSid` is only a test provider identifier. It is
  not proof of delivery to a real customer.
- Missing or invalid emulator configuration fails closed at emulator/T-C
  startup.
- An unreachable emulator or T-C test target returns a bounded technical
  failure to the admin action and never invokes a fallback path.
- A disabled emulator action returns a generic rejection and performs no
  provider or business work.
- A duplicate synthetic inbound identifier follows the existing duplicate
  receipt behavior and cannot create a second processing item or outbound
  send.

## Transaction ownership

- `twilio_emulator` owns no NovaOrders transaction and has no business
  database.
- The admin route owns no commit, rollback, lease, outbox or provider
  transaction. It only invokes the authenticated emulator control API and
  reads the bounded status projection.
- The existing NovaOrders provider coordinator remains the sole owner of
  inbound receipt/deferred-work acceptance.
- The existing worker and outbound dispatcher remain the owners of outbound
  leases, provider calls and conditional finalization.
- The T-C adapter remains the only component that translates the canonical
  outbound command into a provider Messages API call; in emulator mode its
  call goes to the emulator, never to Twilio.

## Observability

The emulator and admin action SHALL emit bounded structured events through
the existing safe catalogue. Events distinguish control accepted, control
rejected, emulator outbound accepted and emulator technical failure. They
must omit message text, addresses, credentials, signatures, URLs, provider
payloads, raw exception text and arbitrary test input.

The admin status response may expose the bounded simulated outbound text to
the authenticated test console because it is the purpose of the test tool;
that text must not enter operational event lines or exception logs.

## Expected files

- `twilio_emulator/` service/package and focused tests.
- `commerce_adapter/app/config.py`, outbound provider seam and inbound
  control integration.
- `backend/config/settings.py` and the central Twilio transport seam for the
  explicit emulator mode.
- `backend/routers/admin_pilot_orders.py` or a focused service/router module
  for the explicit emulator action and status projection.
- `backend/templates/admin_pilot_orders/detail.html` and its bounded browser
  polling behavior.
- `backend/observability/events.py` plus focused observability tests.
- `backend/tests/test_admin_pilot_orders_panel.py` and focused T-C/core tests.
- `openspec/specs/admin-pilot-twilio-emulator/spec.md` after sync.

## Focused tests

- The emulator generates valid Twilio-shaped test credentials and never logs
  them.
- The emulator signs the complete inbound form and the T-C accepts the
  signature.
- The emulator rejects arbitrary inbound target URLs and invalid control
  authentication.
- T-C emulator mode returns a fake SID without importing or invoking the
  real Twilio SDK; real mode remains unchanged.
- The central adapter emulator mode is opt-in and never falls through to a
  real provider call.
- The admin action preserves the local-only route and sends only through the
  emulator/T-C path.
- The admin action rejects unavailable commerce, inactive installation,
  missing emulator configuration and cross-commerce identity mismatch.
- A simulated inbound produces the existing receipt, deferred processing,
  outbox and worker-driven outbound state.
- Duplicate simulated inbound delivery creates no second receipt, outbox row
  or simulated send.
- Status polling is scoped to the exact selected order/session and returns
  only the bounded simulated delivery state and response text.
- No test path sends a request to a real Twilio host or calls
  `Client.messages.create` in emulator mode.

## Validation commands

```text
PYTHONPATH=. venv/bin/python -m pytest twilio_emulator/tests commerce_adapter/tests/test_outbound_route.py commerce_adapter/tests/test_webhook_route.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_outbound_message_dispatcher.py backend/tests/test_production_observability.py -q
PYTHONPATH=. venv/bin/ruff check twilio_emulator commerce_adapter backend/routers/admin_pilot_orders.py backend/services backend/config backend/observability/events.py backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q twilio_emulator commerce_adapter backend/routers/admin_pilot_orders.py backend/services backend/config backend/observability/events.py
openspec validate add-admin-pilot-twilio-emulator --strict
git diff --check
```

## Rollback and reversibility

Rollback is a code-only revert plus disabling the emulator mode and admin
emulator action. The existing local-only admin chat, real T-C transport,
central Twilio transport and durable provider rows remain available. No
database migration or provider credential rotation is required.

## Deferred limitations

- The emulator is a cost-free transport test harness, not a simulator of
  Twilio carrier delivery, WhatsApp behavior, delivery receipts or provider
  latency.
- The first version does not emulate asynchronous Twilio status callbacks;
  the fake SID and existing outbox state are sufficient for the admin test
  result.
- Automatic long-term test history, replay tools and multi-tenant emulator
  administration remain out of scope.
