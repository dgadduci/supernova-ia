# Tasks: global delivery method administration

## 1. Specification and authoritative boundary

- [x] 1.1 Add `metodos-entrega` and administrative-panel spec deltas for
  global list/create/edit behavior, immutable code, global ordering, security,
  and historical isolation.
- [x] 1.2 Extend the existing repository/service with a typed global update
  operation for description, active state, and global non-negative order.
- [x] 1.3 Preserve service-owned atomic commit/rollback; do not add a
  migration, change the JSON API, or mutate bridge/order data.

## 2. Browser administration

- [x] 2.1 Add closed global-delivery panel projections and authenticated list,
  create, and edit routes under `/admin/catalog/metodos-entrega`.
- [x] 2.2 Add bounded list/form templates plus navigation and `/admin` landing
  entries, reusing Basic auth, same-origin, exact-path CSRF, autoescape, and
  POST/redirect/GET.
- [x] 2.3 Keep edit code read-only and ensure global IDs—not association
  IDs—are used for global delivery URLs.

## 3. Focused verification

- [x] 3.1 Add focused service and panel tests for create/edit validation,
  immutable code, duplicate handling, rollback, authentication, CSRF,
  same-origin enforcement, redirects, and escaped errors.
- [x] 3.2 Add regressions proving global deactivation/order edits preserve
  `ComercioMetodoEntrega` state/order and `Pedido.id_metodo_entrega`, and that
  the existing JSON API read/create contract remains unchanged.
- [x] 3.3 The implementer runs the exact commands in `proposal.md` locally
  and supplies complete output for review. Do not commit, sync, archive, or
  deploy.
