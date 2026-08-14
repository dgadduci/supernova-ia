# Design: pilot order operations panel

## Decision

Use a server-rendered FastAPI/Jinja2 administrative panel, backed by one typed
read projection. It is the smallest usable operator interface already
supported by project dependencies and avoids a new frontend deployment,
browser API-token handling, and a duplicate API/client data model.

```text
browser
  -> panel-only administrative authentication
  -> bounded list/detail router
  -> typed read-only projection service/repository
  -> existing pedido/session/customer/catalog/payment/delivery/provider tables
```

The panel does not call the message pipeline, any existing mutating service,
or the provider dispatcher. It has no forms that mutate state.

## Authentication

The existing `X-Admin-Token` protects JSON clients but cannot safely
authenticate ordinary navigation. The panel SHALL use an HTTP Basic challenge
only on its own `/admin/pilot/orders` route family. Its password is validated
against the same configured admin token with constant-time comparison; the
username is ignored. It creates no cookie, token persistence, URL parameter,
or parallel credential. Authentication failures use the same generic detail as
the existing dependency and send `WWW-Authenticate: Basic`.

The panel's Basic credential is never forwarded to a JSON route or included in
templates. This narrowly adapts browser transport while retaining one admin
secret and leaving every existing route's `X-Admin-Token` contract unchanged.

## Projection and bounds

The list query starts from `Pedido` and joins its exact `Session`, `Cliente`
and `Comercio`. Its default is the seven most recent calendar days in the
commerce timezone, newest first, with a page size of 25; `page_size` may be
25, 50 or 100, and the result is capped at 100. The operator can filter by:

- inclusive `from` / `to` dates, capped to a 31-day range;
- exact positive `comercio_id`;
- one closed `EstadoPedido` value.

Malformed/oversized filters return a readable validation error without any
query. The list does not filter by client name, WhatsApp, free text, or IDs
other than an exact commerce id. This intentionally avoids turning the panel
into a broad PII search interface.

Detail lookup uses only the selected positive `pedido_id`; it eager-loads the
Pedido's exact foreign-key relations and lines. Missing ids result in a
not-found page. It does not find a different pedido by client, commerce,
session or message.

## Detail fields and message history

The projection has one explicit typed model and renders:

| Section | Fields |
|---|---|
| Commerce | id, `nombre_fantasia`, `nombre_corto` |
| Client | id, name, WhatsApp, active flag |
| Session | id, active/closed state, start and last-movement timestamps |
| Order | id, state, dates, scheduled delivery, address and general observation |
| Lines | line id, product name, presentation description, quantity, unit price and line observation |
| Fulfilment | delivery method id/description and payment method id/description, each possibly absent |
| Provider history | inbound receipt timestamp/provider/channel and outbound timestamp/sequence/body/state/attempts/delivery state/time/failure category-code |

The provider-history query filters exact `cliente_id` + `comercio_id`, and
orders receipts/outbound rows by their recorded timestamps. It shows no raw
inbound content: no such durable field exists. An outbound row is shown beneath
its exact receipt when the foreign key exists. The enclosing section labels
the collection “historial del cliente y comercio” and explicitly notes that
inbound receipts are not session-linked in the schema; the UI never claims
they occurred in the selected session.

## Rendering and errors

Jinja auto-escaping is mandatory. The layout is plain responsive HTML/CSS
served from the application; no JavaScript is required. Outbound body text is
visually marked as customer-visible content and may be expanded by the
authenticated operator; it is not embedded in HTML attributes, URLs, or logs.
All values are server formatted in the selected commerce timezone where
available, falling back to the application timezone only for display.

No query/service/repository in this change controls a transaction. A technical
database/template exception is logged only through existing safe server
handling and renders a generic error page without exception text, PII or
content. No “best effort” cross-client/commercial lookup occurs.

## Tests

Focused tests shall prove:

- unauthenticated, invalid and missing-configured-token panel requests fail;
  valid Basic authentication succeeds and existing `X-Admin-Token` JSON API
  behavior is unchanged;
- list default/order/filter/pagination bounds and invalid filter behavior;
- one exact detail projection joins the requested fields and leaves absent
  payment/delivery/optional observations legible;
- correct line labels/quantities and client/commercial isolation;
- receipt metadata plus outbound rows render chronologically and raw inbound
  text, provider IDs, tokens, lease values, exception text and diagnostics
  never render;
- template escaping and no mutating form/route/service method, commit,
  rollback, flush, refresh, begin or close call;
- bounded default query does not load unrelated order lines/history.

## Debug-console amendment

### Three-column detail and safe execution state

The existing exact order-detail query remains the sole source for the selected
Pedido, Session, Cliente and Comercio. Its typed result gains a
`PendingContextDebugView`, built from the selected session's persisted fields
only. It has no raw JSON field and exposes only the following closed/derived
values:

| Value | Representation |
| --- | --- |
| context | `none`, a supported context literal, or `unsupported` |
| pending encoding | `empty`, `valid`, or `invalid` |
| active work | closed intent/status literals or `none` |
| requirements | pending and completed counts only |
| candidate state | candidate count only |
| queue | queue length only |
| version | parsed schema version only when valid |
| consistency | `none`, `consistent`, or `inconsistent` |

Malformed pending JSON is represented as `invalid`; its validation error and
payload never render. Context/intent/status values that are not documented
closed values render as `unsupported`, not as raw database content. This
allows an operator to see context state without exposing source text,
observation/address values, candidate IDs, product names or any other pending
payload.

The detail template becomes a responsive CSS grid with columns
`minmax(16rem, 30%) minmax(16rem, 30%) minmax(20rem, 40%)`. The left column is
the local-test chat, the centre column contains the current detail sections,
and the right column contains execution state. Existing chronological provider
history stays in the order-detail column and retains its explicit
client+commerce limitation. On a narrow viewport the grid stacks; no desktop
or external frontend framework is introduced.

### Local-test message boundary

```text
authenticated panel page for exact pedido
  -> POST same-origin local-test route with custom request header
  -> reload/revalidate exact Pedido -> Session association
  -> existing process_incoming_message_with_responses(db, exact_session, text)
  -> normal caller-owned transactional message processor commits business turn
  -> return mapped customer response JSON to browser-only transcript
```

The route is mounted beneath the existing Basic-authenticated panel family and
uses a small request schema with a bounded nonblank string. It does not invoke
the existing generic HTTP endpoint through an internal HTTP request: that
endpoint locates an active session by client/comercio and may choose a session
other than the selected order. Instead, the debug route resolves the selected
Pedido and revalidates all of these invariants before invoking the existing
response-orchestrator seam:

1. Pedido id is the exact positive path id and exists;
2. its linked Session exists and is active;
3. `session.id_pedido` equals that exact Pedido id;
4. the Pedido is `borrador`;
5. session/client/comercio relations are internally consistent.

Any business mismatch returns a generic closed local-test rejection; it must
not search for, reuse or mutate another session/Pedido. The existing
transactional message processor remains the sole commit/rollback owner for a
valid test turn. The panel route, state view service and template must not
call transaction-control methods.

The local-test request never enters `ProviderInboundMessageCoordinator`, so
it creates no provider receipt, deferred processing row, outbound row, worker
lease or Twilio request. Browser JavaScript appends the operator input and
mapped customer responses with `textContent`; it uses no local storage,
cookie, URL parameter or durable transcript. A custom request header is
required so cross-origin form posts cannot invoke the state-changing route;
authentication remains HTTP Basic and the route emits no new application logs
or observability events.

### Tests for the amendment

- exact detail projection renders safe pending-context summaries for empty,
  valid, malformed and inconsistent persisted combinations without mutation;
- raw pending JSON, source text, values, candidate IDs/labels, diagnostics,
  environment/configuration values and secrets never render;
- the 30/30/40 layout and local-test warning render with escaped values;
- missing/wrong Basic auth, missing custom header, malformed/oversized body,
  closed or mismatched selected session/Pedido, and a foreign target fail
  without calling the pipeline;
- a valid local-test turn calls the existing response orchestrator exactly
  once for the exact selected Session, returns only mapped responses, makes no
  provider/outbox/coordinator call and does not redirect to another active
  session;
- all existing GET list/detail/catalog routes remain read-only and their
  authentication, commerce isolation and timezone contracts continue to pass.
