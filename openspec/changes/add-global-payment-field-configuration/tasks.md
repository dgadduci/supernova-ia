# Tasks: global payment field configuration

## 1. Specification and migration

- [x] 1.1 Extend the `medios-pago` and `medios-pago-api` capability deltas with
  global availability semantics for `titular` and `alias`.
- [x] 1.2 Add a reversible migration adding non-null
  `habilita_titular` and `habilita_alias` with effective `false` defaults, and
  verify existing rows backfill without touching `comercio_medios_pago` or
  `pedidos`.

## 2. Authoritative global catalog boundary

- [x] 2.1 Extend the model, schemas, repository, service, and authenticated
  `/medios-pago` read/create/update surface so both flags are represented and
  validated through one service boundary.
- [x] 2.2 Preserve service-owned atomic commit/rollback and existing duplicate
  code/not-found outcomes; repositories must not finalize transactions.

## 3. Browser administration

- [x] 3.1 Add global payment-method list/create/edit pages under the existing
  catalog panel, reusing its Basic authentication, CSRF nonce, same-origin
  validation, safe rendering, and POST/redirect/GET conventions.
- [x] 3.2 Render flags as availability controls, not required-field controls;
  do not expose or mutate commerce `titular`/`alias` values in this change.

## 4. Focused validation

- [x] 4.1 Add focused model/migration, API/service, browser auth/CSRF,
  rollback, and template tests for existing and new payment methods.
- [ ] 4.2 The user runs the exact commands listed in `proposal.md` locally and
  provides the complete output for review. Do not sync, archive, commit, or
  deploy in this change.
