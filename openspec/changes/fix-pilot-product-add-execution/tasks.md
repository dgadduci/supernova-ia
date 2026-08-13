# Tasks

## 1. Caller-owned product add

- [x] 1.1 Add the session-owned caller-transaction create/increment seam and
  typed business outcomes; leave legacy public methods unchanged.
- [x] 1.2 Route only modern `agregar_producto` through it and preserve current
  customer response mapping.

## 2. Safe operations diagnostics

- [x] 2.1 Add the bounded read-only commerce catalog price-availability view.
- [x] 2.2 Register and emit closed `product_add_execution` through the
  existing catalogue and query path.

## 3. Focused verification

- [x] 3.1 Add service/handler transaction and no-mutation tests.
- [x] 3.2 Add provider-coordinator ambiguity → `Grande` E2E tests for
  price-present and price-unavailable outcomes.
- [x] 3.3 Add panel authorization/isolation/no-mutation and event privacy/
  allowlist tests.
- [x] 3.4 Run every focused pytest, Ruff, compileall and strict OpenSpec
  validation command from `proposal.md`; report complete output.

## 4. Production gate and dependent changes

- [ ] 4.1 After approved deploy, check Mozzarella Grande price availability in
  the panel. If unavailable, stop for separately approved catalog remediation.
- [ ] 4.2 If available, run WhatsApp ambiguity → `Grande` and verify one line
  and success response in the panel.
- [ ] 4.3 Resume the three production checks of
  `fix-pending-context-recovery-and-status-query` only after 4.2 succeeds.
- [ ] 4.4 Resume `implement-product-line-observation-intent` only after 4.3;
  do not archive any change without explicit user approval.
