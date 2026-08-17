## Objective

Eliminate the manual endpoint workflow for configuring, per commerce, the
payment methods and delivery methods already represented by
`ComercioMedioPago` and `ComercioMetodoEntrega`. The authenticated
server-rendered administrative panel will let an operator enable or disable
those associations, edit permitted payment details, and set delivery order.

## Current Execution Path

`/admin/catalog/comercios/{id}` reads the exact commerce configuration through
`AdministrativeCatalogPanelViewService`, but both sections are explicitly
read-only. The JSON read contract at `/comercios/{id}/configuracion` returns
the same scoped associations. Global `MediosPago` owns `activo`,
`habilita_titular`, and `habilita_alias`; the bridge owns the concrete payment
details. Global `MetodosEntrega` owns its catalog order and activation, while
the bridge owns the commerce-specific activation and display order.

Order records reference the global payment/delivery IDs, not bridge rows.
Existing order history therefore remains readable when a commerce
configuration changes.

## Scope

- Add commerce-scoped server-rendered configuration pages/controls under the
  established `/admin/catalog/comercios/{id}` family.
- Allow a globally active payment method to be associated with one exact
  commerce and enabled; allow an existing association to be disabled.
- Permit `titular` and `alias` editing only when the associated global payment
  method respectively enables `habilita_titular` or `habilita_alias`.
- Allow a globally active delivery method to be associated with one exact
  commerce, enabled/disabled, and given a non-negative commerce-specific
  `orden`.
- Preserve existing bridge values when an association is disabled or when a
  global payment availability flag becomes disabled. A disabled flag prevents
  future edits; it does not erase stored values.
- Reuse browser Basic authentication, exact-path CSRF nonce, same-origin
  validation, the existing commerce-detail view, and an application service
  rather than internal HTTP calls.

## Non-Goals

- No global payment or delivery catalog CRUD/redesign, seed data, or migration.
- No change to the JSON `/comercios/{id}/configuracion` read contract or new
  public JSON mutation endpoints.
- No order mutation, historical order rewrite, provider behavior, recognition,
  flavor, or outbound styling change.
- No deletion of bridge rows, automatic creation of disabled associations, or
  arbitrary cross-commerce lookup.

## Shared Boundary and Transaction Ownership

A new commerce payment/delivery configuration application service is the sole
mutation boundary. It resolves the exact commerce, global catalog row, and
existing association in one scope; repositories only query or stage ORM rows.
The service owns one commit/rollback per successful POST because the browser
route has no caller-owned transaction. It refreshes/returns the changed scoped
row only after commit; any exception rolls back the complete attempted change.

The panel never calls its JSON endpoints. The existing JSON read route and
order services are unchanged.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| Globally active payment/delivery method, valid exact commerce form | Create or update only that commerce association and redirect to its exact detail page. |
| Globally inactive catalog method | Preserve any existing association but reject a new enable/edit attempt; do not substitute another method. |
| Payment field disabled globally | Do not render or accept that field; preserve its previously stored value. |
| Invalid `titular`/`alias` or negative delivery order | Preserve prior bridge row and render bounded validation feedback. |
| Unknown commerce, catalog method, or association outside the commerce | Safe not-found/bad-request outcome; no cross-commerce fallback. |
| Database/technical failure | Roll back the whole operation and show a generic escaped error; no partial update or raw exception. |

Disabling an association is a valid business outcome, not a fallback and does
not clear payment details or alter orders. A global catalog deactivation is
not editable here and must not be treated as a commerce-level disable.

## Security, Observability, and Reversibility

All panel mutations require the existing browser Basic boundary, exact POST
path nonce, and same-origin check. Dynamic values are autoescaped; credentials
and raw exceptions are never rendered. No provider calls, customer search,
new event stream, or sensitive logging is introduced.

The change is source-only and reversible by removing the rendered adapters and
their service. It does not delete data or migrate schema. Disabling a bridge
row is reversible by re-enabling it; historical orders retain their global IDs.

## Expected Files

- `backend/admin/routes.py`, `forms.py`, `view_service.py`, and `views.py`
- `backend/templates/admin_catalog_panel/comercio_detail.html` plus focused
  payment/delivery configuration templates if necessary
- a focused repository/application service under `backend/repositories/` and
  `backend/services/`
- focused panel, service, and existing API/order regression tests
- this change's OpenSpec artifacts

## Focused Tests and Validation

- A commerce can only mutate its own association; a forged foreign association
  ID cannot affect another commerce.
- A globally active method can create an enabled bridge association; disabling
  it preserves stored payment details and an existing delivery order.
- Payment fields render and persist only when the corresponding global flag is
  true; tampered disabled-field input is rejected without clearing data.
- Delivery `orden` is required to be an integer `>= 0`; invalid input and a
  database failure roll back all attempted changes.
- Global catalog deactivation and order history are not mutated by panel use.
- Browser Basic authentication, CSRF nonce, same-origin rejection, escaped
  errors, and redirect-after-POST remain enforced.

The user will run these focused validations locally after implementation:

```text
venv/bin/python -m pytest backend/tests/test_administrative_catalog_panel.py backend/tests/api_smoke.py
venv/bin/ruff check backend/admin backend/repositories backend/services
venv/bin/python -m compileall backend/admin backend/repositories backend/services
venv/bin/openspec validate add-commerce-payment-delivery-admin --strict
git diff --check
```

## Deferred Limitations

Global delivery-catalog administration, bulk association import, requiredness
rules for payment details, and exposing these edits through JSON APIs remain
deferred. The next phase may revisit only after usage demonstrates a need.
