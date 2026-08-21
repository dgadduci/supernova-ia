# Proposal: bootstrap a clean Twilio Emulator inbound test from Admin/Pilot

## Objective

Add a bounded Admin/Pilot action that starts a provider-shaped inbound test
from an existing active client and commerce, so the normal emulator → T-C →
NovaOrders path creates the session and draft order. The panel must not create
database records directly or bypass the real inbound pipeline.

## Current execution path

The Admin/Pilot order detail page currently operates on an existing Pedido.
Its `Enviar por Twilio Emulator` action requires that Pedido to be
non-`borrador`, so it cannot start the first inbound that creates a session and
draft order. The standalone emulator already exposes the authenticated
`POST /internal/emulator/inbound` control surface; it signs and forwards a
Twilio-shaped form to the configured T-C webhook. The provider worker then
creates the active session and draft Pedido when the inbound is processed.

## Scope

- Add a clearly labelled bootstrap form to the authenticated Admin/Pilot
  surface.
- Accept `cliente_id`, `comercio_id` and a bounded inbound message body. The
  two IDs are the operator-selected test identity; the body is required to
  exercise the inbound pipeline.
- Resolve the client's canonical E.164 address and the commerce's active
  dedicated Twilio channel server-side.
- Validate active client, available commerce, dedicated channel, active T-C
  installation and explicit emulator configuration before any downstream call.
- Reject a pair that already has an active Session, rather than creating a
  second concurrent order context.
- Ask the existing emulator control surface to deliver the inbound. The
  existing T-C webhook, provider coordinator, worker and outbound dispatcher
  remain authoritative for session/order creation and response delivery.
- Return a bounded synthetic inbound identifier and a safe accepted/pending
  result. The panel may refresh the order list to reveal the resulting Pedido.
- Add focused tests and bounded observability without recording message text,
  addresses, credentials or arbitrary input.

## Non-goals

- No direct Admin/Pilot `Pedido`, `Session` or `Cliente` creation endpoint.
- No direct database insert, state mutation, migration or new persistence
  model.
- No bypass of T-C signature validation, NovaOrders ingress, provider worker,
  outbox or emulator outbound transport.
- No automatic closing, replacement or mutation of an existing active
  Session/Pedido.
- No changes to production, Railway services, variables, domains or secrets.
- No change to the existing order-detail emulator action or local-only chat.

## Shared boundary

```text
Admin/Pilot bootstrap form
  -> NovaOrders authenticated bootstrap route
  -> twilio_emulator /internal/emulator/inbound
  -> T-C Twilio webhook
  -> NovaOrders provider coordinator
  -> existing worker
  -> draft Pedido + outbound outbox
  -> existing T-C outbound emulator path
```

The emulator control token remains server-to-server. The browser never
chooses a webhook URL, destination address, credential, provider SID or
control token.

## Authoritative outcomes and fallback

### Valid business outcome

- `accepted`: the emulator accepted the inbound control command. The existing
  T-C and NovaOrders pipeline is responsible for later processing and order
  creation.

### Rejections

- Invalid IDs or message body.
- Missing/inactive client.
- Unavailable commerce.
- Missing/inactive dedicated channel or T-C installation.
- Existing active Session for the selected client/commerce pair.
- Disabled or incomplete emulator configuration.

All rejection and transport failures return the same bounded browser-safe
message. They never fall back to local processing or real Twilio.

### Technical failures

Emulator timeout, unreachable T-C webhook, malformed control response or any
unexpected downstream failure is an unavailable result with no direct order
creation.

## Transaction ownership

The bootstrap route does not call `commit`, `rollback`, `flush`, `refresh`,
`begin` or `close`, and it does not create a Session or Pedido. The emulator
owns only its HTTP forwarding operation. The existing provider inbound
coordinator owns acceptance, and the existing worker transaction owns session,
draft Pedido and outbound staging.

## Observability

Emit only the existing bounded Admin/Pilot emulator outcome event with closed
outcomes such as `submitted`, `rejected` and `unavailable`. Reasons may be
closed categories such as `invalid_target`, `active_context`,
`emulator_disabled` or `transport`; do not include client/commerce IDs,
addresses, message bodies, credentials, URLs or exception text.

## Expected files

- `backend/routers/admin_pilot_orders.py` — authenticated bootstrap route and
  bounded request/response models.
- `backend/services/admin_pilot_emulator_service.py` — target resolution and
  active-context guard, reusing existing channel/client/configuration seams.
- `backend/templates/admin_pilot_orders/list.html` and/or `base.html` —
  bootstrap form and bounded result handling.
- `backend/tests/test_admin_pilot_orders_panel.py` and focused emulator tests.
- `openspec/changes/add-admin-pilot-emulator-inbound-bootstrap/` — this
  proposal, design, spec delta and tasks.

## Focused tests

- Form renders only for the authenticated Admin/Pilot surface.
- Valid client/commerce IDs submit one authenticated emulator inbound with
  server-resolved E.164 addresses and the operator message body.
- The provider path is not called for invalid/inactive client, unavailable
  commerce, missing dedicated channel, missing installation, active context or
  disabled emulator configuration.
- A valid inbound returns a bounded synthetic identifier and never returns
  credentials, addresses or message text.
- The route does not create or mutate a Session/Pedido and does not own the
  database transaction.
- The browser renders escaped plain text, prevents duplicate submission and
  refreshes the order list only after accepted submission.

## Validation commands

The implementer must run and report complete output for:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_service.py -q
PYTHONPATH=. venv/bin/ruff check backend/routers/admin_pilot_orders.py backend/services/admin_pilot_emulator_service.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_service.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py backend/services/admin_pilot_emulator_service.py
openspec validate add-admin-pilot-emulator-inbound-bootstrap --strict
git diff --check
```

## Rollback and reversibility

Disabling emulator mode removes the bootstrap action's availability and
prevents all downstream calls. Removing the panel route and form requires no
migration and leaves existing sessions, pedidos, T-C and real provider paths
unchanged.

## Deferred limitations

The first version intentionally does not create a client, create a commerce,
close an existing active context or offer a browser-side credential editor.
The operator must use an existing active client and an available commerce with
the dedicated channel already configured.
