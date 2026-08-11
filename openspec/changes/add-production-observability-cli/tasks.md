# Tasks

## 1. Proposal and contracts

- [ ] 1.1 Define the versioned allowlisted operational-event schema and event
  catalogue for provider worker, outbound, callback, LLM/Ollama and database
  technical boundaries.
- [ ] 1.2 Define query CLI outcomes, input validation, safe output and
  Railway CLI integration boundary.
- [ ] 1.3 Define platform-log versus durable-message retention ownership and
  read-only inventory contract.

## 2. Implementation

- [ ] 2.1 Add the shared safe event formatter and narrow emitters without
  changing delivery, callback, worker or transaction behavior.
- [ ] 2.2 Add the bounded Railway query CLI and operator documentation.
- [ ] 2.3 Add the read-only durable provider-message retention inventory CLI.
- [ ] 2.4 Configure/document finite Railway retention and query defaults;
  preserve safe no-content output.

## 3. Verification

- [ ] 3.1 Add focused tests for redaction/allowlists and event contracts.
- [ ] 3.2 Add focused tests for query CLI outcomes and Railway failure safety.
- [ ] 3.3 Add focused tests for inventory counts and no-mutation guarantees.
- [ ] 3.4 Run the focused pytest, Ruff, compileall and strict OpenSpec
  validation commands from the proposal.
- [ ] 3.5 Perform one controlled production query after deployment and record
  only its safe aggregate outcome.

## 4. Deferred

- [ ] 4.1 Do not implement deletion of durable provider-message data until a
  separate retention/purge OpenSpec is approved with a chosen retention
  window, legal/support policy, dry-run/apply process and rollback plan.
