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

## Debug-console amendment (2026-08-13)

The deployed panel made it possible to confirm an order-line-selection
production defect: after the valid initial ambiguity for `quitar_producto`, a
size-only reply such as `Chica` or `Grande` remains pending and repeats the
same clarification. This is not a Twilio transport defect. The existing
provider history alone is too slow and incomplete for economical iteration,
while raw JSON endpoints are unsuitable for the pilot operator.

This amendment extends the existing authenticated detail page with a bounded
operator debug console. It deliberately changes only this panel from a
read-only surface into an explicitly labelled, tightly scoped local-test
surface; it does not make the JSON APIs public or turn the panel into a
general administration console.

### Added scope

- Render the detail as three responsive columns: 30% local-test chat, 30%
  current order detail, and 40% safe execution-state view. Narrow screens may
  stack the columns without losing information.
- Show a typed, privacy-bounded summary of the selected session's
  `context_type` and `pending_intents`: pending-state validity/presence,
  active intent and status, candidate count, pending/completed requirement
  counts, queue length, schema version when valid, and a closed consistency
  state between `context_type` and active pending work. Continue showing the
  selected session/pedido states and last movement already present.
- Add one fixed **local test channel** to the selected-order page. An
  authenticated operator may submit a bounded text turn only for that exact
  active session, client, commerce and draft Pedido. It invokes the existing
  transactional incoming-message response orchestration directly and renders
  its customer responses in an in-page, browser-lifetime transcript.
- The chat must visibly state that it is not WhatsApp/Twilio, creates no
  provider receipt, no deferred provider processing record, no outbox row and
  no provider delivery. The message/response transcript is not persisted or
  sent to any provider; only ordinary business state changes made by the
  existing message pipeline are durable.

### Additional safety and non-goals

- The state panel SHALL NOT render raw `pending_intents` JSON, source text,
  resolved values, candidate IDs/labels, queue payloads, diagnostics,
  exception detail, environment variables, configuration values, tokens,
  provider identifiers or secrets. “Execution state” means typed business
  state, never `os.environ`.
- The local test channel is a fixed internal mode, not a selectable or
  persisted `CanalWhatsapp`. Existing persisted channels are routing
  authorities for provider traffic and MUST NOT be reused, fabricated or
  changed by this panel.
- The test route SHALL revalidate the exact selected session and Pedido at
  submission time. It must reject a closed/missing session, a non-draft
  Pedido, or an association mismatch; it must not fall back to another active
  session for the same client/comercio.
- The route uses the existing panel Basic authentication plus a same-origin
  custom request header. It accepts a bounded plain-text payload, records no
  new logs/events, and inserts displayed transcript text through escaped DOM
  text rather than HTML interpolation.
- No reset, cancel, close, manual context edit, direct handler/resolver call,
  LLM bypass, receipt/outbox creation, provider send, worker invocation,
  migration, general channel selector or durable chat storage is authorized.
- Correcting size-only order-line selection is a separate pending corrective
  change. This console provides the controlled reproduction path; it does not
  change that business behavior.

### Paused production gates

The production-message gates of
`fix-pilot-order-line-category-recognition`,
`fix-pending-context-recovery-and-status-query`, and
`implement-product-line-observation-intent` are paused until this amendment
has been approved, implemented, reviewed and deployed. The chat is then used
to reproduce and correct the size-only line-selection defect before any
further WhatsApp testing. This pause does not authorize an archive of any
change.

### Expected files and focused validation for this amendment

Expected implementation is limited to the existing panel router/view service
and detail/base templates, plus their focused tests. A small panel-local
request/view schema is allowed only if it keeps the router free of untyped
payloads. It SHALL NOT modify the provider coordinator, worker, Twilio
adapter, persisted channel models, existing generic incoming-message endpoint,
database schema or migrations.

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_incoming_messages_endpoint.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_remaining_fastapi_surface_security.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_incoming_messages_endpoint.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_remaining_fastapi_surface_security.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py
openspec validate add-pilot-order-operations-panel --strict
```

## Console-refresh amendment (2026-08-14)

The deployed local-test console is sufficient to reproduce the pending
selection defect, but two presentation gaps make repeated diagnosis slower:
the volatile transcript can grow before reaching its maximum height, and the
safe execution-state column remains a snapshot from the initial page render
after a successful local turn changes ordinary business state.

### Objective and scope

- Keep the transcript viewport at one fixed, responsive height. Additional
  turns scroll only inside that viewport; the chat column and the surrounding
  three-column layout MUST NOT grow because of transcript content.
- After every successful local-test turn, update the existing execution-state
  values in place from a newly projected, typed, privacy-bounded snapshot for
  the exact selected Session. The browser keeps the volatile transcript and
  does not need a full-page reload.
- Reuse `PendingContextDebugView` and the existing local-test route. A narrow
  typed response model is allowed if it makes the returned snapshot explicit
  rather than returning an untyped raw dictionary.

### Boundary, privacy and fallback

The route continues to process only the exact active Session and its own draft
Pedido through `process_incoming_message_with_responses`; that processor
remains the sole transaction owner. The pre-turn loader keeps the
``borrador``-only eligibility contract — a pedido that is already
``ingresado`` (or any other non-draft state) MUST be rejected before the
processor is invoked. Only after the processor returns normally may the
route project the updated safe execution-state summary, using a separate
post-turn loader that enforces identity by ``session.id`` AND
``session.id_pedido == pedido_id`` only — it MUST NOT re-check
``borrador``, because a legitimate confirm-order turn legitimately
leaves the pedido in ``ingresado``. The post-turn loader MUST NOT search
for a successor session, another active session for the same
cliente/comercio, or any fallback target. The response SHALL contain
closed values already permitted in `PendingContextDebugView`; it SHALL
NOT contain raw `pending_intents`, source text, resolved values,
candidate IDs, queue entries, diagnostics, exception detail,
configuration, credentials or provider data.

The browser updates only the existing state cells with text APIs. It must not
render response data as HTML, save it in browser storage, poll, add a general
state endpoint, or silently reload the page. A rejected local submission or a
technical failure keeps the existing displayed snapshot and uses the current
generic error behavior; it must not claim a new snapshot was applied.

### Non-goals

This amendment does **not** add cancel/reset/close/create-session controls,
manual context edits, a new lifecycle endpoint, changes to Pedido or Session
business rules, provider/outbox/worker/Twilio behavior, durable chat storage,
polling, migrations, or changes to the paused production gates. It does not
correct the size-only order-line-selection defect.

### Expected files and focused validation

Implementation is limited to the existing panel router and base/detail
templates as needed for the typed response and in-place update, plus their
focused tests. The existing view service may be touched only to reuse or
serialize the already-approved closed execution-state contract. No generic
incoming-message endpoint, provider component, business handler, resolver,
model, migration or new router family may change.

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_remaining_fastapi_surface_security.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_remaining_fastapi_surface_security.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py backend/services/pilot_order_operations_view_service.py
openspec validate add-pilot-order-operations-panel --strict
git diff --check
```

The amendment is source-only and reversible by reverting the local-test
response/UI changes; it does not alter durable state beyond the ordinary
business mutation already performed by a valid local test message.
