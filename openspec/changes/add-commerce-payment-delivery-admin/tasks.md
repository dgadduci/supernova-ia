## 1. Domain boundary

- [x] 1.1 Inspect/add the smallest focused repository methods for exact
  commerce, global payment/delivery catalog rows, and scoped bridge rows.
- [x] 1.2 Add `CommercePaymentDeliveryConfigurationService` with typed,
  commerce-scoped payment and delivery operations, validation, one
  commit/rollback boundary, and no order mutation.
- [x] 1.3 Add focused service/repository tests for creation, enable/disable,
  field-gating, order validation, commerce isolation, and rollback.

## 2. Browser panel

- [x] 2.1 Extend typed panel views to show active global candidates and retain
  inactive global associations as read-only history.
- [x] 2.2 Add exact GET/POST configuration routes and typed form parsing under
  the existing catalog panel authentication/CSRF boundary.
- [x] 2.3 Add payment/delivery configuration templates or bounded detail-page
  controls with clear global-vs-commerce state labels and POST/redirect/GET.
- [x] 2.4 Update the commerce detail page from read-only sections to scoped
  configuration entry points without altering catalog/flavor flows.

## 3. Verification

- [x] 3.1 Add focused panel tests for Basic auth, path-bound CSRF, same-origin
  validation, escaped errors, redirects, field availability, and isolation.
- [x] 3.2 Add regression tests proving the configuration read API and order
  payment/delivery history contracts are unchanged.
- [x] 3.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check`; include full results in the implementation report.
