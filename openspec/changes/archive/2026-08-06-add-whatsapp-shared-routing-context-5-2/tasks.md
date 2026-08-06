## 1. Persistence

- [x] 1.1 Add the channel-scoped customer context model with its unique key,
  restrictive foreign keys, lifecycle fields and exact pending-text field.
- [x] 1.2 Register the model and add one focused reversible migration from the
  verified current Alembic head.

## 2. Scoped activation service

- [x] 2.1 Add a repository confined to customer-channel context reads/writes.
- [x] 2.2 Add typed outcomes and a service that validates active client/channel,
  resolves an exact active shared membership and preserves caller transaction
  ownership.
- [x] 2.3 Enforce idempotent same-code behavior and immutable conflict behavior
  for a different valid commerce code.
- [x] 2.4 Correct active-client validation and remove unreachable in-service
  `IntegrityError` race translation; missing/inactive clients return
  `invalid_context` without context mutation.

## 3. Isolation and preservation tests

- [x] 3.1 Test uniqueness, migration reversibility and channel-scoped context.
- [x] 3.2 Test every activation outcome, code revocation and inactive commerce.
- [x] 3.3 Prove no transaction-control, session/order/client-creation or
  business-pipeline invocation, and prove pending original-text preservation.
- [x] 3.4 Add focused tests for nonexistent and inactive client; both must
  return `invalid_context`, leave no context row and invoke no routing lookup.

## 4. Validation

- [x] 4.1 Re-run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; record exact outputs.

## Deferred approved roadmap

- [ ] 5.3 Manual selection and explicit commerce switching.
- [ ] 5.4 Provider-message receipt, idempotency and common non-transactional
  core.
- [ ] 5.5 Signature-validated Twilio webhook/TwiML.
- [ ] 5.6 Outbound delivery, callback states and retries.
