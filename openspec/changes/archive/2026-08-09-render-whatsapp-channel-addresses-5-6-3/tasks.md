## 1. Render the WhatsApp provider wire address

- [x] 1.1 In `backend/services/twilio_outbound_adapter.py`, render canonical
  sender and recipient E.164 values as `whatsapp:+E.164` only in the Twilio
  `messages.create` call. Keep all source values, supported arguments, result
  mapping and exception classification intact.

## 2. Pin the provider-boundary contract

- [x] 2.1 In `backend/tests/test_twilio_outbound_dispatcher.py`, update the
  strict successful-send seam assertions to require exact WhatsApp channel
  addresses for both `to` and `from_`, while retaining the exact four-keyword
  call-shape proof.
- [x] 2.2 Preserve the real REST-exception and TypeError technical-failure
  proofs; do not add live Twilio calls or log test addresses/bodies.

## 3. Local validation and report

- [x] 3.1 Run every exact command in `proposal.md` locally and report complete
  output, distinguishing unchanged integration-fixture failures.
- [x] 3.2 Report modified files, tests changed and all validation results. Do
  not commit, sync, archive, modify Railway/Twilio variables, or run a
  production dispatch pass.
