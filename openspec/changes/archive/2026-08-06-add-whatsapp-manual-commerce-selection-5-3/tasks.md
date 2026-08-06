## 1. Context state

- [x] 1.1 Add the nullable restrictive pending-switch commerce field and index
  to the existing channel-scoped customer context model.
- [x] 1.2 Add a reversible migration from the verified current Alembic head;
  do not alter existing selections or pending messages.

## 2. Scoped repository and service operations

- [x] 2.1 Extend existing repositories only with channel-scoped active
  membership reads and context pending-target staging operations.
- [x] 2.2 Add typed option, selection and switch outcomes to the existing
  shared-channel routing service boundary.
- [x] 2.3 Implement manual option listing and first selection by active
  membership id, with active client/channel/commerce validation.
- [x] 2.4 Implement request, confirmation and cancellation of an explicit
  switch, including target revalidation at confirmation.
- [x] 2.5 Preserve byte-identical pending text and caller-owned transactions;
  do not invoke the business pipeline.

## 3. Focused tests

- [x] 3.1 Cover options and membership/channel/commerce isolation.
- [x] 3.2 Cover manual initial selection, same-selection idempotency and
  original-message preservation.
- [x] 3.3 Cover switch request, target replacement, confirmation,
  cancellation, no-pending-switch and stale-target fail-closed behaviour.
- [x] 3.4 Cover inactive/missing clients and static no-transaction/no-pipeline
  boundaries.

## 4. Validation

- [x] 4.1 Run focused pytest for the Phase-5.2 and new Phase-5.3 services.
- [x] 4.2 Run Ruff and `compileall` on every touched Python file.
- [x] 4.3 Run strict OpenSpec validation and `git diff --check`; report exact
  outputs and any pre-existing failure separately.

## Deferred approved roadmap

- [ ] 5.4 Provider-message receipt, idempotency and common non-transactional
  core.
- [ ] 5.5 Signature-validated Twilio webhook/TwiML.
- [ ] 5.6 Outbound delivery, callback states and retries.
