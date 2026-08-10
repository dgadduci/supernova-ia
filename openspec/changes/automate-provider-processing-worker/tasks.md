# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect the current durable receipt -> inbound CLI -> outbox ->
  outbound CLI execution path and its manual-production evidence.
- [x] 1.2 Define the opt-in worker boundary, ordering, failure behavior,
  observability, rollback and non-goals.
- [x] 1.3 Obtain approval of the proposal before implementation.

## 2. Implementation (after approval)

- [x] 2.1 Add strict typed worker settings and focused settings validation.
- [x] 2.2 Add the bounded worker loop that delegates only to the existing
  inbound/outbound CLI seams, preserving inbound-before-outbound order.
- [x] 2.3 Add entrypoint enablement, startup validation and child supervision
  without changing disabled behavior.
- [x] 2.4 Add focused tests for bounds, ordering, safe failures, disabled mode,
  supervision contract and redacted observability.
- [x] 2.5 Review scope, transaction ownership, privacy and deploy surface.

## 3. Validation and controlled production check

- [ ] 3.1 User runs focused pytest, Ruff, compileall and strict OpenSpec
  validation locally and provides complete output.
- [ ] 3.2 Deploy only with the flag disabled; verify normal web health and
  manual CLI recovery remain available.
- [ ] 3.3 Enable the worker explicitly in Railway, verify Alembic is at head,
  then test one WhatsApp receipt through delivered outbound without manual
  commands or duplicates.
- [ ] 3.4 Review Railway logs/state, disable/redeploy rollback readiness, and
  obtain separate authorization before sync/archive.
