# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect `origin/main`, the public order/order-line routers, settings,
  dependencies, the provider webhook boundary, and relevant archived admin
  endpoint OpenSpec.
- [x] 1.2 Confirm that public order-management routes lack application
  authentication while Twilio has a separate signature boundary.
- [x] 1.3 Define scope, denial outcomes, no-fallback behavior, transaction
  ownership, safe observability, focused tests, deployment verification, and
  rollback.
- [x] 1.4 Obtain approval for the order and order-line router scope.
- [x] 1.5 Obtain approval of this OpenSpec before implementation.

## 2. Implementation

- [x] 2.1 Add the optional, no-default administrative-token setting and safe
  validation/loading behavior.
- [x] 2.2 Add a reusable constant-time FastAPI authorization dependency with
  fixed `401` and `503` outcomes and no database/transaction/log access.
- [x] 2.3 Apply the dependency at router scope to `pedidos.py` and
  `pedido_productos.py`; do not alter Twilio routes.
- [x] 2.4 Add focused tests covering absent configuration, absent/blank/wrong
  credentials, accepted credentials, no session/service work on denial, and
  unchanged valid state-transition behavior.

## 3. Validation and handoff

- [ ] 3.1 Minimax 3 runs the exact focused pytest, Ruff, compileall, and strict
  OpenSpec validation commands from `proposal.md` locally and reports complete
  output.
- [ ] 3.2 Codex reviews code, tests, transaction boundaries, non-leakage,
  scope, and complete validation output.
- [ ] 3.3 Obtain separate authorization before configuring Railway secrets,
  deploying, syncing, or archiving.
