# Tasks

## 1. Proposal and contracts

- [x] 1.1 Define the versioned allowlisted operational-event schema and event
  catalogue for provider worker, outbound, callback, LLM/Ollama and database
  technical boundaries.
- [x] 1.2 Define query CLI outcomes, input validation, safe output and
  Railway CLI integration boundary.
- [x] 1.3 Define platform-log versus durable-message retention ownership and
  read-only inventory contract.

## 2. Implementation

- [x] 2.1 Add the shared safe event formatter and narrow emitters without
  changing delivery, callback, worker or transaction behavior.
- [x] 2.2 Add the bounded Railway query CLI and operator documentation.
- [x] 2.3 Add the read-only durable provider-message retention inventory CLI.
- [x] 2.4 Configure/document finite Railway retention and query defaults;
  preserve safe no-content output. (CLI defaults and platform retention
  ownership documented in the two CLIs' docstrings; the actual Railway
  retention window is configured at the platform level.)

## 3. Verification

- [x] 3.1 Add focused tests for redaction/allowlists and event contracts.
- [x] 3.2 Add focused tests for query CLI outcomes and Railway failure safety.
- [x] 3.3 Add focused tests for inventory counts and no-mutation guarantees.
- [x] 3.4 Run the focused pytest, Ruff, compileall and strict OpenSpec
  validation commands from the proposal.
- [x] 3.5 Perform one controlled `query_production_logs --event
  outbound_attempt_outcome` after deployment and record only its safe
  aggregate outcome. Production commit `a906a28` deployed successfully;
  the controlled inbound returned HTTP 200, the query returned an
  `accepted` event for outbox id 71, and the customer confirmed receipt.

## 4. Deferred

- [ ] 4.1 Do not implement deletion of durable provider-message data until a
  separate retention/purge OpenSpec is approved with a chosen retention
  window, legal/support policy, dry-run/apply process and rollback plan.
