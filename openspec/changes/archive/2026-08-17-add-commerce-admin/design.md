# Design: commerce administration

## Context

The panel has a configuration surface only after a commerce exists. The
existing JSON creation service already owns validation, duplicate detection,
status resolution, and transaction semantics, so the browser adapter should
reuse it rather than create a parallel write path.

`whatsapp` is used for channel routing and `slug` is a stable catalog
identity. Basic profile editing must not be treated as permission to change
either.

## Decisions

### D1 — Reuse and minimally extend `ComercioService`

The browser create form calls `ComercioService.create`. Add one typed update
method whose signature permits only business profile, address, locale, and
`estado_id`. It validates an exact commerce and state, commits once, and
rolls back failures. The repository does not own transactions.

### D2 — Routing identity is immutable after creation

The create form accepts the existing required `whatsapp` and `slug`. The
edit form displays both read-only and neither route nor service update accepts
them. Tampered values cannot change persistence.

### D3 — Status is a closed typed choice

The panel read service projects exact `EstadoComercio` IDs and labels. Forms
submit IDs, never status strings; the mutation service still verifies that the
ID exists to contain stale/tampered requests.

### D4 — No onboarding side effects

Creation writes exactly one `Comercio`. It does not create or alter a
channel, catalog, flavor, payment/delivery association, order, session, or
provider resource. Existing explicit flows retain their own boundaries.

### D5 — Reuse panel security/error conventions

All POSTs inherit Basic Auth and same-origin enforcement and use a nonce bound
to the exact action path. Expected validation re-renders the exact form with
fresh nonce and escaped feedback. Persistence failures roll back and render a
generic safe error.

## Interaction

```text
authenticated browser
  -> Basic auth + same-origin + exact POST nonce
  -> /admin/catalog/comercios/nuevo or /{id}/editar
  -> ComercioService -> ComercioRepository
  -> one commit + refresh, or rollback
  -> /admin/catalog/comercios/{id}
```

No channel, order, catalog, bridge, or provider component is on this write
path.

## Failure Handling

- Invalid form: no mutation; re-render the exact form with bounded feedback.
- Unknown commerce/status: safe not-found/bad-request outcome, with no
  fallback by slug, WhatsApp, or status name.
- Duplicate identifiers on create: retain existing conflict semantics.
- Technical failure: rollback and generic escaped error.
- Status updates are valid business edits but must not cause channel/order/
  association mutation.

## Risks and Deferred Work

The primary risk is exposing routing identity through a general profile form.
The narrow update signature and immutable edit fields prevent it. A future
WhatsApp/slug change needs explicit routing effects, collision handling,
auditability, and rollback.
