# Tasks
## 1. Specification and approval

- [x] 1.1 Inspect the classifier contract, dispatcher, provider/session staging, transaction owners, models, repositories, response mappers, and relevant archived specs.
- [x] 1.2 Define explicit activation, safe non-mutating outcomes, unique-session ordering, preservation, and multi-intent boundary.
- [x] 1.3 Obtain approval before implementation.

## 2. Implementation

- [x] 2.1 Add the narrowly scoped `iniciar_pedido` dispatcher branch and successor-session orchestration without a new transaction owner.
- [x] 2.2 Add deterministic response mapping for successful successor creation and active-draft continuation.
- [x] 2.3 Add focused dispatcher and PostgreSQL-backed transition/provider rollback tests.
- [x] 2.4 Review transaction ownership, commerce/client isolation, no-copy behavior, and one-active-session preservation.

## 3. Validation and handoff

- [x] 3.1 User runs the focused pytest, Ruff, compileall, and strict OpenSpec validation commands from the proposal locally.
- [x] 3.2 Review the complete validation output and implementation scope.
- [ ] 3.3 Obtain separate authorization before deploy, sync, or archive.
