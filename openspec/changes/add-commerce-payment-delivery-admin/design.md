# Design: commerce payment and delivery administration

## Context

The database already separates global catalogs from commerce choices. The
global payment flags answer whether `titular`/`alias` are meaningful; values
remain on `ComercioMedioPago`. `ComercioMetodoEntrega.orden` is a required,
non-negative per-commerce ordering value. The existing detail projection
already loads both bridge collections with their catalog rows and keeps their
respective ordering rules.

The missing piece is only a browser mutation adapter and a shared application
operation. Adding a migration, moving fields, or writing directly from a
template would duplicate or violate these boundaries.

## Decisions

### D1 — Configure one exact catalog method at a time

The commerce detail page lists current associations and offers a scoped
configuration action for globally active catalog rows. Each POST names the
exact commerce and global row in its route. The service resolves both; it
never trusts an association ID alone and never searches a different commerce.

For a missing association, submitting `activo=true` creates it. A missing
association with `activo=false` is a no-op validation outcome rather than an
automatic disabled bridge row. This avoids filling every commerce with inert
associations while allowing the operator to enable any current global option.

### D2 — Global activity gates new commerce configuration

Only globally active catalog rows are offered for new configuration. Existing
rows whose catalog method later becomes inactive remain visible as historical
configuration, but are read-only in this change. This preserves data without
allowing a commerce form to re-enable a globally withdrawn option.

### D3 — Payment availability gates both rendering and acceptance

The payment form includes `titular` only if `habilita_titular` is true and
`alias` only if `habilita_alias` is true. The service receives the global row
and rejects a submitted value for a disabled field, including a forged POST.
When a flag is false, the service leaves the stored bridge value untouched.
Neither flag makes the field required; blank permitted input normalizes to
`None`.

### D4 — Delivery order belongs to the commerce bridge

The delivery form validates an integer `orden >= 0` independently from the
global catalog order. An enabled new association needs a valid order. Existing
rows may be disabled while retaining their last order. Equal orders are valid:
the established read order uses `(orden, association.id)` as tie-breaker.

### D5 — One service-owned atomic mutation

`CommercePaymentDeliveryConfigurationService` uses a focused repository to
resolve and stage only scoped bridge rows. It commits once and rolls back on
every exception. This explicit ownership is appropriate because the route's
`get_session` caller does not own a transaction. The service returns enough
typed result state for POST/redirect/GET, but the panel re-reads the exact
commerce after redirect.

### D6 — Preserve order and payment history

No bridge row is deleted. Toggling `activo`, altering a permitted payment
detail, or changing delivery order never writes `Pedido`, global catalog rows,
or other commerces. Existing order records refer to global IDs and keep their
historical selection regardless of a later commerce configuration update.

## Interaction Diagram

```text
authenticated browser
  -> Basic auth + same-origin + exact POST nonce
  -> /admin/catalog/comercios/{comercio}/(medios-pago|metodos-entrega)/{global}
  -> CommercePaymentDeliveryConfigurationService
  -> scoped repository -> bridge row + global catalog row
  -> one commit or rollback
  -> redirect to /admin/catalog/comercios/{comercio}
```

## Failure Handling

- Missing commerce/global row or mismatched association: safe bounded outcome;
  no alternate ID, commerce, or catalog-code lookup.
- Expected form validation: no commit, re-render the exact form with escaped
  feedback and a fresh nonce bound to its POST path.
- Global payment flag disabled/inactive catalog method: reject form mutation,
  preserve stored bridge data, and never silently clear it.
- Unexpected persistence error: rollback and render a generic safe error.

## Risks and Deferred Work

The main risks are trusting a client-supplied association scope, clearing
values when availability changes, and confusing global with per-commerce
activity/order. Exact route resolution, service-side gating, and separate
view labels address those risks. Bulk operations and global delivery catalog
management are deliberately deferred.
