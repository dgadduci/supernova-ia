# Proposal: add global delivery method administration

## Objective

Provide an authenticated, server-rendered administrative surface for the
global `MetodosEntrega` catalog: list, create, and edit delivery methods. An
operator can create a method with `codigo`, `descripcion`, `orden`, and
`activo`, then later edit every field except its immutable `codigo`.

## Current Execution Path

`MetodosEntrega` is already the global delivery catalog. It has a unique
`codigo`, a description, a non-negative global `orden`, an `activo` flag, and
timestamps. `MetodoEntregaRepository` reads and creates catalog rows;
`MetodoEntregaService` validates trimmed create input and owns commit/rollback;
the token-protected JSON API at `/metodos-entrega` lists, gets, and creates
rows.

The browser panel currently has global administration only for payment
methods. It does use global active delivery rows as candidates when configuring
an exact `ComercioMetodoEntrega`, where that bridge owns a separate `activo`
and non-negative commerce-specific `orden`. Inactive global rows already
appear as read-only historic associations. `Pedido.id_metodo_entrega` always
references the global catalog row, never a bridge row.

## Scope

- Add browser list, create, and edit pages under
  `/admin/catalog/metodos-entrega`.
- Expose global `codigo`, `descripcion`, `orden`, and `activo` in typed panel
  views; accept `codigo` only on creation.
- Extend the existing delivery-method service/repository with one typed update
  operation for `descripcion`, `orden >= 0`, and `activo`.
- Add the catalog entry to the existing admin navigation and `/admin` landing
  page.
- Reuse the established Basic-auth, same-origin, exact POST-path CSRF nonce,
  autoescape, bounded-error, and POST/redirect/GET conventions.

## Non-Goals

- No schema migration, deletion, bulk import, catalog redesign, or code
  rename.
- No change to the existing JSON API contract or new JSON mutation endpoint.
- No mutation of `ComercioMetodoEntrega`, including its `activo` or its
  commerce-specific `orden`.
- No order mutation, historical rewrite, provider behavior, recognition,
  flavor, or outbound-styling work.

## Shared Boundary and Transaction Ownership

`MetodoEntregaService` remains the sole global-catalog create/update boundary.
The browser panel calls it directly as an HTTP/rendering adapter; it does not
call the JSON API internally. The service commits once after a successful
mutation, refreshes the row, and rolls back the whole operation on exceptions.
`MetodoEntregaRepository` only queries or stages ORM rows.

Global catalog edits do not write bridge rows or `Pedido`. In particular,
global `orden` is distinct from the commerce bridge `orden` and never replaces
it. A global deactivation makes existing commerce associations historic and
read-only through the already-established detail projection; it does not
disable, delete, or re-order them.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| Valid unique create | Persist one global row and redirect to the global list. |
| Valid edit of exact global ID | Update only its description, global order, and active state; keep code unchanged. |
| Unknown global ID | Bounded not-found outcome; no code lookup or alternate row. |
| Blank text, duplicate code, or `orden < 0` | Preserve prior state and render bounded validation feedback. |
| Global deactivation | Preserve bridges and existing orders; show scoped associations only as historical configuration. |
| Database/technical failure | Roll back the attempted catalog mutation; show generic escaped feedback and no raw exception. |

There is no fallback catalog method. A technical error, an inactive method, or
an invalid form must never select or mutate another global method, a commerce
association, or an order.

## Security, Observability, and Reversibility

All panel mutations retain the existing browser Basic authentication,
same-origin validation, and exact-path nonce. Templates autoescape dynamic
values; neither credentials nor raw exceptions are rendered or logged. This
change introduces no provider call, customer-data read, event stream, or
sensitive telemetry.

The change is source-only and reversible by removing the browser adapter and
the service update operation. It does not delete data. An operator can
reactivate a global row later; bridge data and historical order references
remain intact throughout.

## Expected Files

- `backend/admin/routes.py`, `forms.py`, `view_service.py`, and `views.py`
- `backend/admin/index_routes.py`
- `backend/templates/admin/admin_index.html`
- `backend/templates/admin_catalog_panel/base.html`
- new delivery-method list and form templates in
  `backend/templates/admin_catalog_panel/`
- `backend/repositories/metodo_entrega_repository.py`
- `backend/services/metodo_entrega_service.py`
- focused panel/service tests and regressions for commerce delivery and orders
- this change's OpenSpec artifacts

## Focused Tests and Validation

- The global list renders all rows with their global order/state and an exact
  edit link; it never renders bridge IDs as global IDs.
- Authenticated create trims text, rejects duplicate code and `orden < 0`, and
  commits one global row only.
- Edit keeps `codigo` immutable, updates only global description/order/state,
  and rolls back on persistence failure.
- Missing IDs, invalid form input, Basic-auth failure, invalid nonce,
  cross-origin POST, and escaped error rendering retain established behavior.
- Deactivating a global method does not mutate a `ComercioMetodoEntrega` row,
  its commerce order, or a `Pedido.id_metodo_entrega`; commerce projections
  continue to show the association as historical.
- The existing `/metodos-entrega` JSON read/create contract remains unchanged.

The implementer runs these exact commands locally after implementation and
provides complete output for review:

```text
venv/bin/python -m pytest backend/tests/test_administrative_catalog_panel.py backend/tests/test_commerce_payment_delivery_panel.py backend/tests/test_commerce_payment_delivery_regression.py backend/tests/api_smoke.py
venv/bin/ruff check backend/admin backend/repositories/metodo_entrega_repository.py backend/services/metodo_entrega_service.py
venv/bin/python -m compileall backend/admin backend/repositories/metodo_entrega_repository.py backend/services/metodo_entrega_service.py
venv/bin/openspec validate add-global-delivery-method-admin --strict
git diff --check
```

## Deferred Limitations

Deletion, code rename, bulk administration, JSON update/delete endpoints, and
editing per-commerce delivery associations from this global catalog are
deferred. No behavior in the recognition roadmap changes.
