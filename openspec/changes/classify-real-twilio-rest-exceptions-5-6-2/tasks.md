## 1. Translate the real SDK REST exception

- [x] 1.1 In `backend/services/twilio_outbound_adapter.py`, catch the pinned
  SDK's `TwilioRestException` and map retryability from HTTP `status`, not the
  Twilio provider error code. Preserve the existing result categories,
  sanitization and database-free adapter boundary.
- [x] 1.2 Remove or stop relying on the private `_TwilioAPIError` test marker;
  do not add a broad catch-all or alter transport classification.

## 2. Pin the production exception contract

- [x] 2.1 In `backend/tests/test_twilio_outbound_dispatcher.py`, construct
  SDK-realistic `TwilioRestException` values with synthetic safe data and
  prove 429 retryable, 5xx retryable and other 4xx terminal behavior.
- [x] 2.2 Prove provider code is safe observability data rather than the retry
  classifier, preserve the strict normal-send call-shape test, and prove
  `TypeError` remains a technical failure.

## 3. Local validation and report

- [x] 3.1 Run every exact command in `proposal.md` locally and report complete
  output; identify the unchanged integration-fixture failures separately if
  they recur.
- [x] 3.2 Report modified files, tests changed, all validation results and
  any unrun command. Do not commit, sync, archive, change Twilio/Railway
  configuration, or run a production dispatch pass.
