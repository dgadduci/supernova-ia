# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect `origin/main`, active and archived order/closure/intent/
  WhatsApp OpenSpecs, and the current inbound-to-outbox execution path.
- [x] 1.2 Verify the existing classifier enum/prompt already declares
  `consultar_estado_pedido`, while dispatcher/mapper support is absent.
- [x] 1.3 Define authoritative state outcomes, association/isolation checks,
  no-search fallback, transaction ownership, observability, validation,
  rollback, and deferred limits.
- [x] 1.4 Obtain user approval before implementation.

## 2. Implementation

- [x] 2.1 Add only the `CONSULTAR_ESTADO_PEDIDO` branch to the existing initial
  dispatcher and delegate to the approved read-only orchestrator.
- [x] 2.2 Add the narrow session-owned order-status orchestrator with explicit
  missing/stale/foreign business outcomes and all six persisted states.
- [x] 2.3 Add a deterministic non-sensitive response builder and route only
  this intent through the shared outbound response mapper.
- [x] 2.4 Add focused tests for every state, association isolation,
  non-mutation/transaction neutrality, pending-context priority, and
  local/outbox response equivalence.

## 3. Validation and handoff

- [x] 3.1 Minimax 3 runs the exact focused pytest, Ruff, compileall, and strict
  OpenSpec validation commands in `proposal.md` locally and reports complete
  output.
- [x] 3.2 Codex reviews changed scope, code, tests, static checks,
  transaction ownership, isolation, and the complete local validation output.
- [x] 3.3 User authorized commit, sync, production deployment, controlled
  WhatsApp validation, and archive; no retention/purge work was performed.
