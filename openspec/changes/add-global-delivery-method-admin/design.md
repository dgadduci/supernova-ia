# Design: global delivery method administration

## Context

The delivery domain already has the necessary ownership split:
`MetodosEntrega` is global and `ComercioMetodoEntrega` is commerce-scoped.
Their two `orden` values intentionally solve different ordering needs. Orders
reference only `MetodosEntrega`, preserving a stable global foreign key across
changes to commerce configuration.

The missing capability is a browser adapter for the existing global catalog.
The closest established pattern is global payment administration: typed panel
view models, a server-rendered list/form, direct invocation of the shared
application service, browser Basic authentication, CSRF nonce tied to the
POST path, same-origin validation, and redirect-after-POST.

## Decisions

### D1 — Reuse the existing delivery service boundary

`MetodoEntregaService` gains the minimal update operation. It validates and
normalizes description, validates the global non-negative order, resolves the
exact ID, delegates staging to `MetodoEntregaRepository`, and owns a single
commit/rollback lifecycle. The repository does not own a transaction.

The JSON API is deliberately unchanged: it retains list/get/create behavior
and does not acquire a new update endpoint. The new browser routes call the
same service directly rather than making internal HTTP calls.

### D2 — Make `codigo` immutable after creation

The create form submits a bounded `codigo` (1–50 characters); the edit form
shows it read-only and sends no mutable code field. The service update
signature omits `codigo`. This preserves the current catalog identity without
introducing referential or operator ambiguity.

### D3 — Keep global and commerce delivery state separate

The global form edits `MetodosEntrega.activo` and `.orden` only. It never
loads or writes `ComercioMetodoEntrega`. Existing commerce associations of a
globally deactivated row remain stored and appear only in the historical
section, consistent with the completed commerce configuration change. Their
`activo` and `orden` are not inferred, reset, or copied from the global row.

### D4 — Use closed panel projections

`AdministrativeCatalogPanelViewService` projects global rows as
`GlobalMetodoEntregaRow` for the new list and exact edit form. Templates do
not inspect ORM objects. Global identifiers remain explicitly named and no
association ID participates in a global route.

### D5 — Reuse browser form security and error discipline

All routes remain below `/admin/catalog`, inheriting Basic authentication and
same-origin enforcement. Every POST receives a nonce computed for its exact
action URL. Expected validation failures re-render only the exact form with a
fresh nonce and bounded, autoescaped feedback. Unexpected failures roll back
in the service and render a generic bounded error.

## Interaction Diagram

```text
authenticated browser
  -> Basic auth + same-origin + exact POST nonce
  -> /admin/catalog/metodos-entrega[/nuevo|/{id}/editar]
  -> MetodoEntregaService
  -> MetodoEntregaRepository -> MetodosEntrega
  -> one commit + refresh, or rollback
  -> redirect to global list
```

`ComercioMetodoEntrega` and `Pedido` are outside this write path.

## Failure Handling

- Unknown numeric ID: render the established not-found page; never fall back
  to code or another row.
- Invalid/non-positive path ID, blank normalized description, duplicate code,
  or negative/non-integer order: do not call a mutation or commit; return
  bounded form feedback.
- Database failure: rollback all staged state and return generic escaped
  feedback; no raw exception reaches the browser.
- Global inactivation is a valid business outcome, not an error or fallback.
  It must not cascade into bridge/order updates.

## Risks and Deferred Work

The relevant risks are conflating global and bridge IDs, allowing global order
to overwrite commerce order, and treating global deactivation as a destructive
cascade. Closed typed views, an update boundary limited to `MetodosEntrega`,
and explicit regression coverage contain those risks.

Catalog deletion, code rename, batch tools, and JSON update/delete APIs remain
out of scope. This design does not introduce LangGraph or alter Fuzzy/
recognition behavior.
