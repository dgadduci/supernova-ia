# Tasks

## 1. Read-only administrative boundary

- [ ] 1.1 Add the panel-only Basic authentication adapter using the existing
  configured admin token, without modifying existing JSON API authentication.
- [ ] 1.2 Add the bounded list/detail routes and mount them without exposing a
  public data route or a state-changing operation.

## 2. Typed order projection and templates

- [ ] 2.1 Implement the read-only typed projection for exact pedido detail,
  commerce/client/session, lines, payment/delivery and provider history.
- [ ] 2.2 Implement the minimal server-rendered list/detail/error templates
  with escaped values, pagination/filter controls and clear missing-value
  rendering.
- [ ] 2.3 Label provider history correctly, including receipt-only inbound
  metadata and the absence of durable inbound text/session linkage.

## 3. Verification

- [ ] 3.1 Add focused authentication, router, projection isolation/privacy,
  rendering/escaping, filter-bound and no-mutation tests.
- [ ] 3.2 Run every focused pytest, Ruff, compileall and strict OpenSpec
  validation command from `proposal.md` locally; report complete output.

## 4. Operational handoff

- [ ] 4.1 After review and approved deployment, inspect the designated pilot
  order/session using the panel and confirm it shows the required data.
- [ ] 4.2 Resume the paused pending-context production verification only after
  4.1; then follow the original dependent observation production gate.
- [ ] 4.3 Do not add a reset/cancel/close action or archive either prior
  change without a separate approved change and explicit user approval.
