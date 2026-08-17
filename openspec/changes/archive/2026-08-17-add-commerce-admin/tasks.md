# Tasks: commerce administration

## 1. Authoritative boundary

- [x] 1.1 Add `comercio` and administrative-panel spec deltas for browser
  onboarding, exact basic editing, immutable routing identifiers, and status
  isolation.
- [x] 1.2 Extend repository/service with a typed update of only permitted
  profile, address, locale, and status fields; preserve service-owned
  commit/rollback.
- [x] 1.3 Add closed typed views for exact commerce form data and valid status
  options, without channel internals.

## 2. Browser panel

- [x] 2.1 Add create/edit routes and a bounded form below
  `/admin/catalog/comercios`, reusing Basic Auth, same-origin, exact-path
  CSRF, autoescape, and POST/redirect/GET.
- [x] 2.2 Add create/edit entry points from list/detail and show WhatsApp/slug
  read-only after creation.
- [x] 2.3 Preserve existing flavor, catalog, payment, and delivery routes and
  their transaction/ID boundaries.

## 3. Focused verification

- [x] 3.1 Add service/panel tests for valid creation/edit, defaults,
  duplicates, invalid/stale status, rollback, authentication, CSRF,
  same-origin, escaping, and redirects.
- [x] 3.2 Add regressions proving edits cannot mutate WhatsApp/slug, channels,
  orders, catalog, flavor, payment/delivery bridges, or JSON contracts.
- [x] 3.3 The implementer runs the exact commands in `proposal.md`, reports
  complete output, and does not commit, sync, archive, PR, merge, or deploy.
