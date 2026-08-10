# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect the active/archived OpenSpec material, classifier contract, initial and pending dispatchers, response mapper, outbox boundary, and focused tests.
- [x] 1.2 Define authoritative outcomes, pending-context precedence, exact fallback conditions, transaction ownership, observability, and non-goals.
- [x] 1.3 Obtain approval before implementation.

## 2. Implementation

- [x] 2.1 Add the six explicit non-mutating social dispatcher outcomes without changing the classifier contract or pending dispatcher.
- [x] 2.2 Add one pure deterministic social-response builder and map only the approved intents through the existing mapper.
- [x] 2.3 Add focused dispatcher, mapper, and common response/outbox-boundary tests.
- [x] 2.4 Review response ordering, no state mutation, pending-context precedence, generic fallback preservation, and no raw-text observability.

## 3. Validation and handoff

- [x] 3.1 User runs the focused pytest, Ruff, compileall, and strict OpenSpec validation commands from the proposal locally.
- [x] 3.2 Review the full validation output and implementation scope.
- [ ] 3.3 Obtain separate authorization before deploy, sync, or archive.
