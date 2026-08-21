# Proposal: show a scrollable Admin/Pilot Emulator conversation history

## Objective

Replace the current single-result presentation of the Admin/Pilot Twilio
Emulator action with a bounded, chronological conversation list. The panel
must keep the messages sent by the operator and the responses received from
the NovaOrders pipeline visible in the current page so the operator can review
and copy the test history for a later handoff.

## Current execution path

The detail page submits an operator message to the existing
`POST /admin/pilot/orders/{pedido_id}/emulator-test` route. The browser polls
the existing status projection until a terminal state and
`renderEmulatorResult` replaces the Emulator result container with the latest
status, outbound body and provider SID. The submitted message itself is not
kept in that result, and a later turn replaces the previous result. The local
channel already has a separate volatile transcript and is not part of this
change.

## Scope

- Add a scrollable Emulator conversation list to the existing detail page.
- Append each submitted operator message as an `Enviado` entry.
- Associate the entry with its synthetic inbound identifier in volatile
  browser state so repeated polling updates the same turn instead of adding
  duplicate responses.
- Append or update the corresponding bounded `Respuesta recibida`, status,
  provider SID or generic failure outcome using the existing status contract.
- Keep entries chronological and scroll the list to the newest entry after a
  submission or status update.
- Keep the existing Emulator form, asynchronous polling and generic error
  behavior unchanged.
- Keep the list bounded and text-safe so long or repeated tests cannot grow
  the page without limit.

## Non-goals

- No backend route, schema, database, migration, receipt, outbox or worker
  changes.
- No persistence in localStorage, sessionStorage, cookies, URL parameters or
  server-side storage.
- No change to the T-C, Twilio Emulator, real Twilio or outbound pipeline.
- No change to the existing local-only transcript behavior.
- No export endpoint, automatic clipboard write, CSV/JSON download or
  cross-page history.
- No raw provider payloads, credentials, signatures, exception text or
  unbounded message data in server logs or HTTP responses.

## Shared boundary

```text
Existing Emulator form and status polling
  -> existing JSON route contracts
  -> volatile browser turn map
  -> bounded scrollable conversation list
```

The browser remains a presentation layer. The server remains authoritative for
acceptance, processing, outbound status and response text; the new list only
renders the bounded values already returned by the existing contract.

## UI and outcome contract

- The list has a fixed viewport with its own vertical scroll context.
- Every row has a stable role/label distinguishing `Enviado`, `Respuesta
  recibida`, `Estado` or `Error`.
- The submitted text is rendered with `textContent` or an equivalent safe DOM
  API, never `innerHTML` or raw HTML interpolation.
- A submitted message is shown once immediately; polling updates its status
  and adds at most one response for that synthetic inbound identifier.
- `accepted`/`pending` remain visibly pending without inventing a response.
- A bounded outbound body becomes one received-response row when available.
- `retryable` and `terminal`, transport errors and generic rejections become
  bounded error/status rows without exposing internal details.
- The list automatically follows the newest row and remains manually
  scrollable.

## Fallback behavior

If the list container or an optional response field is unavailable, the
existing form submission, status node and generic rejection behavior continue
to work. No new UI failure may retry, bypass or alter the existing provider
pipeline.

## Transaction ownership

No SQLAlchemy session is introduced or accessed by this UI-only change. The
existing route and provider pipeline retain their current transaction
ownership.

## Observability

No new server-side event is required. The conversation list is volatile page
state and must not write message bodies, phone numbers, provider payloads,
credentials or exception text to logs or persistent browser storage.

## Expected files

- `backend/templates/admin_pilot_orders/detail.html` — replace the single
  Emulator result presentation with the accessible scrollable list container
  and bounded handoff copy.
- `backend/templates/admin_pilot_orders/base.html` — add the minimal CSS and
  browser-only turn/list rendering while reusing the existing submit/status
  flow.
- `backend/tests/test_admin_pilot_orders_panel.py` — focused contract tests for
  the list structure, fixed viewport, safe rendering and turn deduplication
  markers.
- `openspec/changes/add-admin-pilot-emulator-conversation-history/` — this
  proposal, design, spec delta and tasks.

## Focused tests

- The enabled detail page renders a dedicated Emulator conversation list with
  accessible list semantics and a scrollable fixed viewport.
- The browser script appends sent messages and renders received responses
  without replacing prior turns.
- Repeated polling for one synthetic inbound identifier does not duplicate a
  response.
- The list uses bounded safe DOM rendering and does not use browser storage or
  URL state.
- Generic rejection, pending status, terminal status, local transcript and
  existing Emulator form contracts remain present.

## Validation commands

The implementer must run and report complete output for:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/ruff check backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py
openspec validate add-admin-pilot-emulator-conversation-history --strict
git diff --check
```

## Rollback and reversibility

The change is browser/template-only and reversible by reverting the two
template changes. Existing server routes, persisted data and provider
behavior remain unchanged.

## Deferred limitations

The first version does not persist history across page reloads, order-detail
navigation or users, and does not add a download/copy control. The operator
can select and copy the visible bounded list manually.
