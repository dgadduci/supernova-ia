## 1. Domain persistence

- [x] 1.1 Add channel mode and `CanalWhatsapp` with canonical provider /
  destination identity, lifecycle and direct dedicated commerce ownership.
- [x] 1.2 Add `ComercioCanalCompartido` with permanent historical routing-code
  uniqueness and rejection for dedicated channels.
- [x] 1.3 Register models and add one reversible migration from the verified
  current Alembic head; do not alter `Comercio.whatsapp`.

## 2. Repository and service boundaries

- [x] 2.1 Correct new-table repository writes so they only add/modify
  caller-owned ORM state and never invoke `flush`, `begin`, `commit` or
  `rollback`.
- [x] 2.2 Correct channel lifecycle operations so registration and
  deactivation preserve caller-owned transaction synchronization; add focused
  tests covering the no-transaction-control boundary.
- [x] 2.3 Enforce dedicated/shared cross-entity invariants and permanent code
  non-reassignment.

## 3. Dedicated resolution

- [x] 3.1 Implement read-only `CommerceChannelResolver` for explicit provider
  and destination input.
- [x] 3.2 Return typed outcomes for resolved, unknown, malformed, inactive,
  unavailable and shared channels; do not inspect sender or message text.
- [x] 3.3 Prove no invocation of local endpoint, classifier, recognizers,
  catalog services, handlers, session creation or transaction methods.

## 4. Focused verification

- [x] 4.1 Declare and test the named active-only partial unique index in both
  `CanalWhatsapp` metadata and the migration, alongside existing uniqueness,
  lifecycle and dedicated/shared invariant coverage.
- [x] 4.2 Add resolver tests for normalization, active dedicated success and
  every non-resolved outcome.
- [x] 4.3 Re-run documented pytest, Ruff, compileall, strict OpenSpec
  validation and `git diff --check`; record exact outputs and failures here.
  - pytest: `54 passed, 9 subtests passed in 0.93s`
  - Ruff: `All checks passed!`
  - compileall: no output, exit 0
  - strict OpenSpec: `Change 'add-whatsapp-channel-routing-5-1' is valid`
  - `git diff --check`: no output, exit 0

## Deferred approved roadmap

- [ ] 5.2 Customer-channel context, shared-code activation and original-message
  preservation: separate approved change.
- [ ] 5.3 Manual selection and explicit commerce switching: separate approved
  change.
- [ ] 5.4 Provider-message receipt, idempotency and common non-transactional
  core: separate approved change.
- [ ] 5.5 Signature-validated Twilio webhook/TwiML: separate approved change.
- [ ] 5.6 Outbound delivery, callback states and retries: separate approved
  change.
