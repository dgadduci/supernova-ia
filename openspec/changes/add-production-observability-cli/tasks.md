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
- [ ] 3.5 Perform one controlled `query_production_logs --event
  outbound_attempt_outcome` after deployment and record only its safe
  aggregate outcome. (Defer until the CLI fix lands in production:
  the CLI previously forwarded `--event` as Railway's `--filter`,
  which is a text search on the envelope `message` field that is
  empty for our structured events and therefore always returned zero
  matches. The CLI now applies `--event` only as a local filter on
  the parsed events; a controlled production query must confirm the
  bounded array is non-empty for `outbound_attempt_outcome` after
  deploy.)

## 4. Deferred

- [ ] 4.1 Do not implement deletion of durable provider-message data until a
  separate retention/purge OpenSpec is approved with a chosen retention
  window, legal/support policy, dry-run/apply process and rollback plan.
