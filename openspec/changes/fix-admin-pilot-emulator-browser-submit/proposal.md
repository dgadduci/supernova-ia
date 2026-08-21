# Proposal: fix Admin/Pilot Twilio Emulator browser submission

## Objective

Make the enabled `Enviar por Twilio Emulator` action submit a valid request
through the existing Admin/Pilot JSON contract and display the bounded
asynchronous status projection in the same page.

## Current execution path

The emulator endpoint declares `payload: EmulatorTestRequest`, so FastAPI
expects a JSON object such as `{"message":"Hola"}`. The detail template
renders the emulator action as a normal HTML form. The existing browser script
only binds `[data-debug-form]`, which is the local-test form; it does not bind
`[data-debug-emulator-form]`. The browser therefore performs a native
`application/x-www-form-urlencoded` submission (`message=Hola`), and FastAPI
rejects the scalar form body with `model_attributes_type` before the emulator
route runs.

The template also does not currently expose the status URL to a browser-side
emulator handler, so the intended bounded polling flow cannot start after a
successful submission.

## Scope

- Add a dedicated browser handler for the emulator form.
- Send `{"message": "..."}` as JSON with same-origin credentials and the
  existing `X-Emulator-Test-Origin: same-origin` header.
- Expose the existing status URL through a non-secret data attribute.
- Poll the existing read-only status endpoint with the returned
  `synthetic_inbound_id` and render only its bounded status, outbound text and
  synthetic provider SID.
- Keep the existing local-test handler and route unchanged.
- Add focused regression coverage for the browser contract and preserve the
  existing route tests.

## Non-goals

- Do not change the Admin/Pilot JSON request or response schemas.
- Do not change the emulator route, emulator service, T-C, NovaOrders,
  coordinator, worker, dispatcher or outbox behavior.
- Do not accept form-urlencoded input as a second route contract.
- Do not expose control tokens, Twilio-shaped credentials, signatures, raw
  exception details or arbitrary operator input in responses or logs.
- Do not modify Railway variables, deployments, production or calibration.
- Do not add a second business-processing or status source of truth.

## Shared boundary

The shared boundary is the Admin/Pilot browser-to-route contract:

- submit: `POST /admin/pilot/orders/{pedido_id}/emulator-test` with a JSON
  object containing only `message`;
- status: `POST /admin/pilot/orders/{pedido_id}/emulator-test/status` with a
  JSON object containing only `synthetic_inbound_id`.

The existing route schemas remain authoritative.

## Authoritative outcomes and fallback behavior

- A valid submit response is accepted only when the HTTP response is
  successful and contains a non-empty `synthetic_inbound_id`.
- Status polling accepts only the existing bounded statuses: `accepted`,
  `processed`, `pending`, `sent`, `retryable` and `terminal`.
- `sent`, `retryable` and `terminal` end polling. Transitional statuses may be
  polled again up to a bounded client-side limit.
- Invalid JSON, an unexpected response shape, an HTTP error or a polling limit
  displays the generic emulator rejection/status message and stops polling.
- The browser never falls back to the local channel, real T-C, central Twilio
  or real Twilio.

## Transaction ownership

Unchanged. The browser remains a caller of the existing Admin/Pilot route. It
does not open, commit, rollback or otherwise own a database transaction.

## Observability and security

Reuse the existing server-side bounded events. The browser may render only the
bounded response fields already defined by `EmulatorTestResponse` and
`EmulatorStatusResponse`. The control token remains server-to-server and never
reaches the browser. No raw validation error, credential, signature, URL,
phone number or unbounded operator input is written to logs or displayed as a
server error.

## Expected files

- `backend/templates/admin_pilot_orders/base.html`
- `backend/templates/admin_pilot_orders/detail.html`
- `backend/tests/test_admin_pilot_orders_panel.py`, for focused regression
  assertions where appropriate
- This OpenSpec change

## Focused tests and validation

The implementer must run and report the complete output of:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/ruff check backend/routers/admin_pilot_orders.py backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py
openspec validate fix-admin-pilot-emulator-browser-submit --strict
git diff --check
```

Tests must prove that the emulator form exposes its status URL, uses the
dedicated emulator selector, preserves the JSON route contract and leaves the
existing local form behavior unchanged. No real provider or external network
call is permitted in focused tests.

## Rollback and reversibility

Rollback is a template/script revert. The existing server routes and local
channel remain available, and disabling emulator configuration continues to
hide the emulator action. No database or Railway rollback is part of this
change.

## Deferred limitations

Browser-level visual verification and a deployed end-to-end emulator message
are deferred until the correction is merged, deployed and explicitly tested in
`core/test`.
