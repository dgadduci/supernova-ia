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
