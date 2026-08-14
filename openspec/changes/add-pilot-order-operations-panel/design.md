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

## Console-refresh amendment (2026-08-14)

### Fixed transcript viewport

The transcript remains a browser-lifetime DOM node, but its CSS uses one fixed
block height with `overflow-y: auto`. It does not use content-driven height or
an expanding min/max range. Long operator/customer text continues to wrap and
the existing append operation scrolls that viewport to its bottom; it does not
resize the grid row, detail column or execution-state column.

### Updated execution-state response

The successful existing local-test boundary gains one typed closed
`execution_state` member alongside its mapped customer `responses`:

```text
validated exact draft Session + Pedido (pre-turn loader keeps borrador gate)
  -> existing transactional response orchestration commits the turn
  -> reload exact Pedido/Session identity (post-turn loader, no borrador gate)
  -> project PendingContextDebugView for that same Session only
  -> return mapped responses + closed execution_state
  -> append escaped transcript lines and replace state-cell textContent
```

The pre-turn loader keeps the ``borrador``-only eligibility contract — a
pedido that arrives in ``ingresado`` (or any other non-draft state) MUST be
rejected before the processor is invoked. The post-turn loader is a separate
helper that enforces identity by ``session.id`` AND
``session.id_pedido == pedido_id`` only and explicitly does NOT re-check
``borrador``: a legitimate confirm-order turn legitimately leaves the pedido
in ``ingresado`` and the panel MUST still surface the refreshed snapshot. The
post-turn loader MUST NOT search for a successor session or another active
session for the same cliente/comercio; if the exact identity is gone it
returns ``None`` so the route can emit the documented generic rejection
without leaking which invariant failed.

`execution_state` has the exact closed fields of `PendingContextDebugView`:
context type, pending encoding, active intent, active status, candidate count,
pending/completed requirement counts, queue length, optional valid schema
version, and consistency. It is not a raw serialization of the Session or its
JSON. The router does not call `commit`, `rollback`, `flush`, `refresh`,
`begin`, `close` or `expire`; the pre-existing message processor remains the
only owner of the transaction.

The browser updates only nodes identified for the pre-existing execution
state. It uses `textContent`, including for the absent-schema-version display,
and never uses `innerHTML`. On a non-2xx response, malformed response or
network failure it leaves those state nodes unchanged; the existing generic
status/error message remains the fallback.

### Focused tests

- CSS/source rendering proves the transcript has a fixed viewport with scroll
  and cannot grow from appended turns;
- successful local-test route responses contain the current closed
  `execution_state` for the exact target and no raw pending payload;
- a successful turn that legitimately flips the pedido from ``borrador`` to
  ``ingresado`` still returns 200 with the mapped responses and a closed
  execution-state snapshot, without searching for a successor session and
  without any router-side transactional control;
- template JavaScript updates every execution-state cell from that response
  using text APIs only, retaining the transcript;
- the post-turn snapshot loader returns ``None`` ONLY when the exact
  Pedido/Session identity is gone (session deleted or re-pointed to another
  pedido); a pedido that is now ``ingresado`` is NOT treated as a rejection;
- rejected, malformed and technical client-side responses do not overwrite
  the existing state cells;
- pre-turn loader rejection (including ``pedido already not in borrador``)
  emits the documented generic rejection without consulting the post-turn
  snapshot loader or the processor;
- existing Basic authentication, same-origin, exact-target, no-provider and
  transaction-ownership contracts remain unchanged.
