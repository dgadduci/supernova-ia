# Proposal: add pilot order operations panel

## Objective

Provide a small authenticated web panel for the pilot operator to inspect
orders and their operational context without assembling FastAPI JSON responses
by hand. It is a read-only diagnostic surface: it makes the current order,
session, commerce/client information, order lines, delivery/payment choices,
and durable provider-message history legible before the paused WhatsApp test
gates resume.

## Current execution path

The deployed application exposes only token-protected JSON routers for
`/pedidos`, `/sessions`, clients and configuration. `GET
/pedidos/{id}/detalle` has order-line labels but does not list orders, join the
session/client/comercio, resolve payment/delivery labels, or present a
conversation timeline. No frontend route, static application, or aggregate
read model exists.

An inbound provider receipt persists provider, timestamp, client, commerce and
channel, deliberately without inbound body text or a session/pedido foreign
key. Durable outbound rows contain the rendered body and link to an inbound
receipt. Therefore a panel can show inbound receipt metadata and full durable
outbound bodies to an authorized operator, but it must not claim an inbound
body or an exact session association that the database does not retain.

## Scope

- Add one server-rendered, administrative, read-only pilot order list and
  detail view; use the existing FastAPI/Jinja2 dependencies rather than adding
  a frontend build, SPA, API gateway, dashboard vendor, or database table.
- Protect the panel with the existing administrative credential through a
  browser-appropriate authentication boundary; it must not place the token in
  a URL, HTML, JavaScript, local storage, logs, diagnostic events, or rendered
  error message.
- List recent orders with bounded pagination and explicit, bounded filters for
  date range, commerce and order state. Each list row includes order id/state,
  session id/state, commerce id/name, client id/name/WhatsApp, creation and
  last-update timestamps.
- Provide a detail view with the requested order metadata: commerce/client,
  session, pedido, all product-presentation lines (product name, presentation
  description, quantity, unit price and any persisted line observation),
  pedido-level observation/address/scheduled delivery, payment and delivery
  method ids plus descriptions, and relevant timestamps.
- Show a chronological provider-history section scoped by the same client and
  commerce. It distinguishes inbound receipt metadata from outbound durable
  messages, shows the outbound delivery state/attempt metadata, and labels the
  association as client+commerce history rather than a proven session timeline.
- Include only useful operational metadata already available in the read path:
  provider/channel id, inbound receipt time, outbound sequence/state/attempts,
  provider delivery status/time and non-secret failure category/code.

## Non-goals

- No write controls: no cancel, reset, close session, create order/session,
  retry delivery, change state, or direct database access. A controlled reset
  action requires separate explicit approval and a separate change after this
  read view proves adequate.
- No migrations, new message persistence, raw inbound-message retention,
  inferred message-to-session association, log reading, LLM, classifier,
  inbound/outbound worker, public webhook, mobile UI, real-time refresh,
  export, search by WhatsApp text, or global analytics/dashboard.
- No reuse of customer-facing response models as a panel contract, no generic
  `dict` payloads, and no relaxation of existing JSON API authentication.

## Shared boundary, privacy and fallback

The panel is a human operations interface, not a second order-processing
pipeline. Its query service reads the existing relational models only and has
no commit, rollback, flush, refresh, begin or close calls; FastAPI's request
dependency remains the transaction/session owner. The existing JSON routers,
provider flows and operational-log privacy policy remain unchanged.

The browser authentication boundary validates the same configured admin token
without exposing it in a URL or client-side storage. An unauthenticated or
misconfigured request returns the same generic administrative failure already
used by protected routes. Templates must escape values. The authenticated
detail view may render customer PII and durable outbound text because the
operator explicitly needs pilot diagnosis; it must never render provider IDs,
admin credentials, lease tokens, raw inbound body (which is not retained),
exception text, or application diagnostics. No panel request may emit the
displayed PII/content to logs or new events.

Missing optional relationships render a clear em dash; a missing Pedido or an
invalid filter is a normal empty/not-found view, not a fallback lookup. Query
failure results in a generic safe server error and does not broaden the query,
guess ownership, or show a partial record as authoritative.

## Expected files

- `backend/routers/admin_pilot_orders.py` and a narrow panel-auth helper
  adjacent to the existing admin dependency if needed.
- `backend/services/pilot_order_operations_view_service.py` plus a typed view
  model/module, and one read-only repository/query seam if it materially keeps
  joins out of the router.
- `backend/templates/admin_pilot_orders/` for list, detail and base/empty/error
  fragments. CSS stays local and minimal; no external assets or CDN.
- `backend/main.py` and public router exports only to mount the protected
  panel.
- Focused router, authentication, query-projection/privacy and template tests.
- A new `pilot-order-operations-panel` spec delta.

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this
project's Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_remaining_fastapi_surface_security.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py backend/main.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py backend/main.py
openspec validate add-pilot-order-operations-panel --strict
```

## Rollback and deferred limitations

This is source-only and reversible by removing the panel router/templates and
its read-query seam. It does not alter existing records or schema. A later,
separately-approved change may add a narrowly validated reset operation if the
operator still needs it; it must not be silently folded into this panel.

## Dependencies and resume gate

This panel is the prerequisite for resuming production WhatsApp verification
of `fix-pending-context-recovery-and-status-query`, and then
`implement-product-line-observation-intent`. Neither prior change may be
archived merely because this panel is delivered. After the panel is deployed,
use it to inspect the designated pilot order/session and only then resume the
previously documented production test sequences.
