# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect active/archived OpenSpec material, classifier contract/prompt, real inbound, pending, transaction, response/outbox, pedido, service, repository, and focused-test paths.
- [x] 1.2 Define authoritative outcomes, deterministic confirmation grammar, isolation, fallback, transaction ownership, observability, rollback, non-goals, and focused validation.
- [x] 1.3 Obtain user approval before implementation.

## 2. Implementation

- [x] 2.1 Add the session-owned draft precondition and pending `order_clear_confirmation` initiation for `vaciar_pedido` in the existing initial dispatcher path.
- [x] 2.2 Add deterministic affirmative/negative pending resolution, preserving pending context for unclear replies and clearing it only after a definitive result.
- [x] 2.3 Add the transaction-neutral, validated all-lines clear handler/service/repository operation and register it with existing pending execution.
- [x] 2.4 Add deterministic customer responses and map only this intent through the shared response mapper/outbox path.
- [x] 2.5 Add focused tests for confirmation, cancellation, invalid/stale outcomes, isolation, atomicity, pending priority, and shared response behavior.

## 3. Validation and handoff

- [x] 3.1 Implementer runs the exact focused pytest, Ruff, and compileall commands from `proposal.md` locally and reports complete output.
- [x] 3.2 Codex reviews implementation, test output, strict OpenSpec validation, changed scope, transaction ownership, and isolation.
- [ ] 3.3 Do not sync, archive, deploy, or commit unless separately authorized by the user.
