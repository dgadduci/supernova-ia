# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect `origin/main`, all router registrations, the deployed
  order-management boundary, health, and Twilio ingress/callback boundaries.
- [x] 1.2 Classify every registered router as public operational, public
  provider ingress, administrative, or already protected.
- [x] 1.3 Define no-fallback outcomes, transaction ownership, privacy,
  expected tests, rollback, and exclusions.
- [x] 1.4 Obtain approval of this change before implementation.

## 2. Implementation

- [x] 2.1 Attach the existing admin dependency at router scope to every
  classified administrative router; do not alter health or Twilio routers.
- [x] 2.2 Preserve the embedding-admin flag as an additional post-auth gate.
- [x] 2.3 Add inventory and representative focused tests for the protected and
  exempt surfaces, denial-before-session behavior, and valid-token behavior.
- [x] 2.4 Update only impacted existing router tests to supply a safe authorized
  dependency override.

## 3. Validation and handoff

- [x] 3.1 Minimax 3 runs focused pytest, Ruff, compileall, and strict OpenSpec
  validation locally and reports complete output.
- [x] 3.2 Codex reviews scope, code, tests, transactions, public exceptions,
  and the complete reported validation output.
- [x] 3.3 Obtain separate authorization before changing Railway configuration,
  deploying, syncing, or archiving.
