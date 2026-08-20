# Proposal: add commerce edge observability

## Objective

Expose the business outcome of the isolated commerce edge as bounded,
machine-readable operational events. Operators must be able to distinguish an
accepted or duplicate inbound event from a business rejection and identify the
closed rejection reason without inferring it from an HTTP `200` or from a blank
log message.

## Current execution path

The T-C adapter receives Twilio's signed form in
`commerce_adapter/app/routes/webhook.py`, normalizes the event, forwards it to
NovaOrders through `commerce_adapter/app/novaorders_client.py`, and maps the
typed result to an empty TwiML response. It currently calls
`logger.info(..., extra={...})` for outcomes, but the deployed Railway
formatter renders only the message and omits those fields.

NovaOrders receives the canonical event in
`backend/routers/internal_commerce_installation.py`. The router resolves the
installation, channel, client and commerce availability, delegates accepted
events to `ProviderInboundMessageCoordinator`, and similarly logs outcome
fields through `extra`. The existing shared JSON event contract in
`backend/observability/events.py` is already consumed by the worker and
outbound dispatcher, but the isolated ingress is not registered in that
catalogue.

## Scope

- Add one closed, versioned inbound-outcome event to the existing NovaOrders
  observability catalogue, including `accepted`, `duplicate`, `rejected` and
  `unreachable` outcomes and a bounded reason token where applicable.
- Emit that event from every NovaOrders isolated-ingress outcome, using the
  existing JSON-line event sink so `backend/cli/query_production_logs.py` can
  parse it.
- Add a small adapter-local JSON-line emitter because the adapter must not
  import NovaOrders backend modules. Replace the adapter's plain outcome log
  calls with the same event name, outcome vocabulary and bounded reason
  vocabulary.
- Preserve the current HTTP status, empty-TwiML, HMAC, idempotency,
  transaction and outbound behavior exactly.
- Add focused tests for event shape, reason allowlists, all outcome branches,
  Railway-visible JSON serialization, and no-secret/no-PII leakage.

## Non-goals

- No database schema, migration, message contract, business decision,
  response-body, TwiML or HTTP-status change.
- No new metrics backend, tracing system, dashboard, alert, log shipping
  service or general logging-formatter migration.
- No raw message body, phone number, provider payload, signature, credential,
  token, URL, LLM content or exception text in any event.
- No change to the central Twilio webhook, outbound dispatcher state machine,
  provider worker cadence or commerce activation state.

## Shared boundary

The shared boundary is the existing isolated inbound outcome decision in the
T-C webhook and NovaOrders ingress. The business code decides the typed result
first; the event emitter observes that result afterward. The emitter never
selects a business outcome, opens a database session, owns a transaction or
changes the response sent to Twilio.

## Outcome and fallback behavior

The authoritative outcome remains the existing typed result and HTTP/TwiML
mapping. The event is observational only:

- The adapter emits one event for each local webhook branch, including
  signature/form/configuration rejection, accepted/duplicate, core rejection
  and core unreachability.
- The core emits one event only after installation authentication, signature
  verification and canonical-payload validation have succeeded and the request
  reaches the existing channel/client/commerce/coordinator decision. Those
  validated business outcomes are `accepted`, `duplicate` or `rejected`.
- Core pre-decision HTTP failures (unknown or inactive installation, missing or
  undecryptable master/envelope configuration, signature failure and canonical
  payload mismatch/validation failure) are not business outcomes and MUST NOT
  be converted into a new core rejection event. When reached through the T-C
  adapter, the adapter observes the existing non-200 response as
  `unreachable` with `reason=core_http_failure`; a malformed successful core
  response uses `core_invalid_response`.

- `accepted` means NovaOrders returned `accepted` and the core created the
  durable receipt; `duplicate` remains a separate outcome.
- `rejected` means a documented business or validation rejection. Its `reason`
  is one of the closed tokens defined by the specification.
- `unreachable` is an adapter-owned transport/contract outcome: the adapter
  could not obtain a usable NovaOrders typed response or the core returned a
  non-success response. The core does not use it for the pre-decision branches
  listed above.

If event validation or serialization fails, the current request result MUST
remain unchanged. The core uses the existing observability failure event; the
adapter emits no sensitive fallback payload and continues its existing
response path. Event failure must never trigger a retry, a second provider
send or a transaction rollback.

## Transaction ownership

The change owns no transaction. NovaOrders keeps the coordinator and router
transaction boundaries unchanged. The adapter emitter performs only bounded
in-memory validation and a single stdout write after the outcome is known.

## Observability contract

Every event is one JSON line with `schema_version`, `event`, `component`,
`timestamp`, `outcome`, and, for rejection/unreachable outcomes, a closed
`reason` token. The event carries no identifier that can reconstruct a phone,
message, secret or provider payload. The reason vocabulary is shared by the
adapter and core so Railway queries can group both services without parsing
free-form text. The existing operational parser SHALL accept exactly the two
catalogued components for this event (`commerce_installation_ingress` and
`commerce_installation_adapter`) and no other component; this does not make
the adapter import NovaOrders code.

## Expected files

- `backend/observability/events.py` — catalogue, allowlists and safe reason
  field for the new event.
- `backend/routers/internal_commerce_installation.py` — emit the canonical
  event at each existing outcome branch.
- `commerce_adapter/app/observability.py` — adapter-local bounded JSON-line
  emitter.
- `commerce_adapter/app/routes/webhook.py` — emit the event at each existing
  adapter outcome branch.
- `backend/tests/test_internal_commerce_installation_ingress.py` and a focused
  observability test module for the core event contract.
- `commerce_adapter/tests/test_observability.py` and the webhook-route tests.
- `openspec/specs/commerce-edge-observability/spec.md` after sync.

## Focused tests

- Core event catalogue accepts every documented outcome/reason pair and
  rejects unknown fields, free-form reasons and sensitive values.
- The existing production-log parser accepts the event with either documented
  component and rejects any other component.
- Adapter emitter produces one parseable JSON line per outcome and never
  includes the body, phone, token, signature, credential or exception text.
- Existing ingress and adapter tests retain their exact HTTP/TwiML behavior
  while asserting the corresponding event.
- An emitter failure leaves accepted/rejected/unreachable behavior unchanged.
- Existing production-log parsing accepts the new core event.

## Validation commands

```text
PYTHONPATH=. venv/bin/python -m pytest commerce_adapter/tests/test_observability.py commerce_adapter/tests/test_webhook_route.py backend/tests/test_internal_commerce_installation_ingress.py backend/tests/test_commerce_edge_observability.py -q
PYTHONPATH=. venv/bin/ruff check commerce_adapter/app/observability.py commerce_adapter/app/routes/webhook.py backend/observability/events.py backend/routers/internal_commerce_installation.py commerce_adapter/tests/test_observability.py backend/tests/test_commerce_edge_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q commerce_adapter/app/observability.py commerce_adapter/app/routes/webhook.py backend/observability/events.py backend/routers/internal_commerce_installation.py
openspec validate add-commerce-edge-observability --strict
git diff --check
```

## Rollback and reversibility

Rollback is a code-only revert of the emitter and catalogue additions. It
does not touch persisted data, provider configuration, installation secrets or
the commerce/channel rows used by the validated test. Existing plain logs and
runtime responses remain available during rollback.

## Deferred limitations

This phase does not add a dashboard or alerting policy and does not guarantee
that every generic Uvicorn access log is JSON. It only makes the isolated
business outcome events queryable and distinguishable. Correlation across an
inbound event and its later outbound message remains the responsibility of the
existing bounded receipt/outbox evidence until a separate observability
change defines a safe correlation identifier.
