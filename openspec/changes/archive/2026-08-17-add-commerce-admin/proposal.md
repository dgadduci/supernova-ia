# Proposal: add commerce administration

## Objective

Add authenticated, server-rendered onboarding and basic profile editing for
`Comercio` under `/admin/catalog/comercios`. An operator can create a
commerce with its existing required data and later edit its profile, address,
locale, and status from the panel.

## Current Execution Path

`ComercioService.create` is the existing authoritative create boundary. It
normalizes text, validates required fields and an exact `EstadoComercio`,
detects duplicate `whatsapp`/ `slug`, and owns commit/rollback. The
token-protected JSON `POST /comercios` uses that service; no update operation
exists.

The panel lists and configures existing commerces (flavor, catalog, payments,
and deliveries), but cannot onboard one or edit its base data. `whatsapp`
participates in channel routing and `slug` is a unique catalog identity.
Orders and associations are scoped by immutable commerce ID.

## Scope

- Add panel routes/forms for commerce creation and exact-commerce basic edit.
- Reuse `ComercioService.create` for browser creation.
- Add the smallest typed update operation for profile, address, `estado_id`,
  `zona_horaria`, `moneda`, and `idioma`.
- Offer valid status rows as closed typed options; service validation remains
  authoritative.
- Keep `whatsapp` and `slug` immutable after creation.
- Reuse browser Basic Auth, same-origin, exact-path CSRF, autoescaping,
  bounded feedback, and POST/redirect/GET.

## Non-Goals

- No migration, deletion, soft-delete, bulk import, global status CRUD, or
  WhatsApp/slug rename.
- No changes to JSON APIs, channel provisioning, flavor, catalog, payments,
  deliveries, orders, provider behavior, recognition, or outbound styling.
- No automatic creation of categories, associations, flavors, channels, or
  provider resources when onboarding a commerce.

## Shared Boundary and Transaction Ownership

`ComercioService` is the sole create/update boundary. Browser routes call it
directly rather than internally calling JSON endpoints. The service resolves
the exact commerce/status, stages only permitted scalar fields, commits once
on success, refreshes after commit, and rolls back on any exception.
Repositories only query or stage ORM data.

Creation inserts only a `Comercio`. Editing does not touch routing
identifiers, another commerce, flavors, catalogs, bridge rows, orders,
sessions, channels, or provider resources.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| Valid create with existing status | Create one commerce and redirect to its exact detail page. |
| Valid edit of exact commerce | Persist only permitted basic fields and redirect to that commerce. |
| Unknown commerce/status or invalid ID | Bounded not-found/bad-request outcome; no alternate lookup or default status. |
| Duplicate WhatsApp/slug on create | Preserve state and show bounded conflict feedback. |
| Invalid profile/address/locale input | Preserve prior state and show bounded feedback. |
| Forged WhatsApp/slug edit | Do not accept it; stored routing identifiers remain unchanged. |
| Database failure | Roll back the entire attempt; expose no raw exception or partial data. |

No failure may silently create an inert commerce, select a different status,
alter routing identity, or mutate related data.

## Security, Observability, and Reversibility

All mutations retain Basic authentication, same-origin validation, and an
exact POST-path nonce. Dynamic values are autoescaped; credentials and raw
exceptions are not rendered. No provider calls, customer-data reads, or new
event stream are introduced.

This is source-only and reversible by removing the panel adapter and update
operation. It deletes no data. Routing-identifier changes are deliberately
deferred for a dedicated, explicitly evaluated change.

## Expected Files

- `backend/admin/routes.py`, `forms.py`, `view_service.py`, and `views.py`
- `backend/templates/admin_catalog_panel/comercios_list.html`,
  `comercio_detail.html`, and a new focused commerce form template
- `backend/repositories/comercio_repository.py`
- `backend/services/comercio_service.py`
- focused panel/service and API/order/channel regressions
- this change's OpenSpec artifacts

## Focused Tests and Validation

- Valid browser creation persists exactly one commerce and redirects to its
  exact configuration page.
- Validation rejects missing/stale status, blank required fields, duplicates,
  invalid locale values, auth/nonce/origin failures, and persistence errors
  without partial writes.
- Exact edit updates only permitted base fields; forged `whatsapp`/`slug`
  input cannot change routing identity.
- Edits do not change flavor, catalog, payment/delivery bridges, orders,
  sessions, channels, or JSON contracts.

The implementer runs locally and reports complete output:

```text
venv/bin/python -m pytest backend/tests/test_administrative_catalog_panel.py backend/tests/api_smoke.py backend/tests/test_commerce_channel_resolver.py backend/tests/test_shared_channel_manual_selection.py
venv/bin/ruff check backend/admin backend/repositories/comercio_repository.py backend/services/comercio_service.py
venv/bin/python -m compileall backend/admin backend/repositories/comercio_repository.py backend/services/comercio_service.py
venv/bin/openspec validate add-commerce-admin --strict
git diff --check
```

## Deferred Limitations

Changing routing identifiers, status catalog management, deletion, channel
provisioning, and bulk administration remain deferred.
