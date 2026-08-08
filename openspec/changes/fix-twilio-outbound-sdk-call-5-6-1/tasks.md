## 1. Correct the provider boundary

- [x] 1.1 In `backend/services/twilio_outbound_adapter.py`, remove only the
  unsupported `idempotency_key` keyword from the Twilio `messages.create`
  invocation. Preserve the four supported arguments, typed result mapping,
  failure classification and all transaction boundaries.

## 2. Pin the real call shape

- [x] 2.1 In `backend/tests/test_twilio_outbound_dispatcher.py`, replace or
  augment the accepted-send test with a strict Twilio-9.10.9-compatible
  Message-create stand-in that cannot accept arbitrary keyword arguments.
- [x] 2.2 Assert the four supported SDK arguments, absence of
  `idempotency_key`, the returned-SID accepted finalization and existing safe
  result fields. Do not add live Twilio calls, credentials or payload logging.

## 3. Local validation and report

- [x] 3.1 Run the exact focused pytest command in `proposal.md` locally and
  provide the complete output.
- [x] 3.2 Run the exact Ruff, `compileall`, strict OpenSpec validation and
  `git diff --check` commands in `proposal.md`; provide complete output and
  distinguish any known pre-existing failure from a new regression.
- [x] 3.3 Report modified files, test names added/changed, validation output,
  and any unrun command. Do not sync, archive, commit, alter Railway or run a
  production dispatch pass.
