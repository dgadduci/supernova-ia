# Proposal: add global payment field configuration

## Objective

Let an administrator define, on every global `MediosPago` record, whether a
commerce may enter `titular` and/or `alias` for that payment method. These
flags govern form availability only; the concrete values remain on the
commerce-to-payment association (`ComercioMedioPago`).

## Current Execution Path

`MediosPago` is the global catalog (`codigo`, `descripcion`, `activo`).
`ComercioMedioPago` is the unique `(comercio, medio_pago)` association and
already owns its per-commerce `activo`, `titular`, and `alias` values. The
authenticated JSON surface at `/medios-pago` only lists, gets, and creates
global rows. The browser panel at `/admin/catalog` reads payment associations
but deliberately does not mutate them. No current rule says whether `titular`
or `alias` applies to a particular global payment method.

## Scope

- Add non-null global Boolean flags `habilita_titular` and `habilita_alias` to
  `MediosPago`, both defaulting to `false`.
- Add a reversible Alembic migration that backfills existing rows to `false`.
- Extend global payment-method create/read/update contracts to expose and
  persist the flags.
- Add an authenticated browser-admin management surface for global payment
  methods, including existing and new rows, reusing the established Basic-auth
  and path-bound same-origin CSRF boundary.
- Preserve the existing JSON `X-Admin-Token` boundary and add only the
  necessary update operation; no internal HTTP calls between panel and API.

## Non-Goals

- No `ComercioMedioPago` mutation, no commerce payment form, and no delivery
  configuration. Those belong to `add-commerce-payment-delivery-admin`.
- No move of `titular` or `alias` to `MediosPago`: they remain per-commerce
  values.
- No required-field semantics. `habilita_*` means a commerce may edit the
  field, not that it must supply it.
- No global payment-method delete, catalog redesign, order mutation, provider
  behavior change, or outbound-styling change.

## Shared Boundary and Transactions

The global payment service remains the authoritative create/update boundary.
It owns the same commit/rollback lifecycle as the existing global create
operation; repositories only stage/query ORM state. The browser adapter calls
that shared service directly. The migration alone owns schema/data changes.

Changing either global flag never changes an existing `ComercioMedioPago` row,
any order, or any historical payment value. A later commerce configuration
phase must reject editing a disabled field while preserving already-stored
values, so re-enabling remains reversible.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| New or existing global method enables a field | Persist the selected Boolean; commerce forms may later expose that field. |
| Global method disables a field | Persist the selected Boolean; do not erase existing commerce values. |
| Unknown global method | Return the existing bounded not-found outcome; no fallback lookup. |
| Invalid form/API input | Preserve prior row and return bounded validation feedback. |
| Database failure | Roll back the full attempted mutation; render/return no raw exception detail. |

No technical failure may silently change either flag, substitute another method,
or mutate commerce associations.

## Observability and Security

No new provider calls, customer-data reads, or event family are required.
Browser mutations retain HTTP Basic authentication, path-bound CSRF nonce, and
same-origin validation. JSON routes retain `X-Admin-Token`. Templates must
autoescape all values and never render credentials or exception details.

## Expected Files

- `backend/models/medios_pago.py`
- a new revision under `backend/alembic/versions/`
- `backend/schemas/medios_pago.py`
- `backend/repositories/medios_pago_repository.py`
- `backend/services/medios_pago_service.py`
- `backend/routers/medios_pago.py`
- focused additions under `backend/admin/` and
  `backend/templates/admin_catalog_panel/`
- focused tests for model/migration, service/router, and browser panel
- this change's OpenSpec artifacts

## Focused Tests and Validation

- Existing and new `MediosPago` rows expose flags defaulting to `false`.
- Upgrade/backfill and downgrade preserve rows and restore the prior schema
  only after removing the added columns.
- Authenticated create/update accepts Boolean flags; invalid/missing rows leave
  data unchanged; database failures roll back.
- Browser Basic auth, CSRF nonce, and same-origin rejection remain enforced
  for all global payment mutations.
- Browser forms render/edit both flags for new and existing rows without
  exposing per-commerce `titular`/`alias` values.

The user runs these exact focused validations locally after implementation:

```text
venv/bin/python -m pytest backend/tests/test_administrative_catalog_panel.py backend/tests/api_smoke.py
venv/bin/ruff check backend/models/medios_pago.py backend/schemas/medios_pago.py backend/repositories/medios_pago_repository.py backend/services/medios_pago_service.py backend/routers/medios_pago.py backend/admin
venv/bin/python -m compileall backend/models/medios_pago.py backend/schemas/medios_pago.py backend/repositories/medios_pago_repository.py backend/services/medios_pago_service.py backend/routers/medios_pago.py backend/admin
venv/bin/alembic -c backend/alembic.ini upgrade head
venv/bin/alembic -c backend/alembic.ini downgrade -1
venv/bin/openspec validate add-global-payment-field-configuration --strict
git diff --check
```

## Rollback and Deferred Limitations

Application rollback consists of disabling/removing the browser management
surface while retaining the harmless `false` flags. Migration downgrade drops
only the two added global columns; it does not alter commerce associations or
orders. Per-commerce payment/delivery configuration and enforcement of these
flags in commerce forms are explicitly deferred to the next change.
