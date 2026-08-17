# Design: global payment field configuration

## Context

The data model already separates a global payment-method catalog from
per-commerce configuration. `titular` and `alias` are correctly located on
`ComercioMedioPago`: a transfer alias belongs to the receiving commerce, not
to every commerce that uses the global `TRANSFERENCIA` method. What is absent
is a global rule describing which of those per-commerce fields apply.

The existing browser catalog panel is server-rendered, Basic-authenticated,
and protected on mutations by a deterministic nonce bound to the POST path
plus same-origin validation. The existing global JSON payment API uses the
admin token and a service-owned transaction. This change extends those
boundaries; it does not create a separate management pipeline.

## Decisions

### D1 — Store two availability flags on `MediosPago`

Add `habilita_titular` and `habilita_alias` as non-null Boolean columns with
Python and server defaults of `false`. Their independent values support a
method that permits only one field without encoding method-specific rules in a
commerce form.

### D2 — Flags govern availability, not requiredness

`true` permits a later commerce form to render and accept the corresponding
field. `false` means that form must not allow edits to it. Neither state makes
the field required. Requiredness is deliberately deferred rather than inferred
from a payment type.

### D3 — Preserve association-owned values when a flag changes

Changing a global flag neither clears nor copies `ComercioMedioPago.titular`
or `.alias`. This is reversible, protects historical operator configuration,
and avoids a global edit mutating many commerce rows. The future commerce
phase will preserve values while blocking their edit whenever the corresponding
flag is false.

### D4 — Global catalog remains the sole authority for flag mutation

The global payment service validates and persists both flags for create and
update. The panel invokes that service directly, as an HTTP/rendering adapter.
The JSON router invokes the same service. Repositories do not commit or roll
back; the service performs one atomic commit and rolls back on failure.

### D5 — Add a reversible additive migration

The migration adds both columns as non-null with a temporary/effective server
default `false`, ensuring existing production rows acquire the safe value.
Downgrade drops only those columns. No migration reads, rewrites, or deletes
commerce associations, catalog codes, or orders.

### D6 — Reuse the existing browser security boundary

The global management pages live under the established `/admin/catalog`
family and use `require_admin_browser_basic` and
`require_same_origin_panel_form`. Every state-changing form contains a nonce
computed for its exact POST path and requires a matching same origin. The JSON
API remains protected by `require_admin_token`.

## Interaction Diagram

```text
browser administrator
  -> Basic auth + CSRF/same-origin
  -> admin catalog payment form
  -> MediosPagoService
  -> MediosPagoRepository -> MediosPago

JSON administrator
  -> X-Admin-Token
  -> /medios-pago create/update
  -> MediosPagoService (same boundary)
```

## Failure Handling

- Missing row: service raises the existing not-found domain error; adapter
  returns a bounded `404`, with no alternate lookup.
- Invalid payload/form: adapter preserves prior state and shows/returns a
  bounded validation result.
- Duplicate `codigo`: existing conflict behavior remains unchanged.
- Database error: service rolls back its transaction; the panel reports a
  generic safe error and the JSON adapter preserves its existing policy.

## Risks and Deferred Work

The primary risk is treating a global availability flag as a per-commerce
field requirement. This design avoids that by using explicit `habilita_*`
names and by retaining association values on disable. The future commerce
configuration change must enforce availability for edits and must not invent
method-specific fallback values. It will also own payment association creation,
activation, delivery configuration, and delivery ordering.
