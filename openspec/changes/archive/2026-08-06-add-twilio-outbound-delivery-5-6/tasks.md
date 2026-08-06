## 1. Durable response contract

- [x] 1.1 Add the outbound-message model, migration, repository and immutable
  typed state/result contracts.
- [x] 1.2 Extract the reusable response mapper from the local response
  orchestrator without changing its rendered messages.
- [x] 1.3 Stage ordered outbox rows inside the existing 5.4 transaction and
  return empty first-processing TwiML from 5.5.

## 2. Dispatch and retry

- [x] 2.1 Add due-row lease/claim and conditional finalization operations.
- [x] 2.2 Add the narrow Twilio REST adapter and typed failure classification.
- [x] 2.3 Add the bounded explicit retry dispatcher and outbound settings.

## 3. Delivery callbacks

- [x] 3.1 Add a signature-validated Twilio status callback adapter/route.
- [x] 3.2 Record only monotonic callback transitions and idempotent no-op
  outcomes.

## 4. Focused tests

- [x] 4.1 Cover atomic staging, duplicate suppression and local-endpoint
  compatibility.
- [x] 4.2 Cover leasing, accepted sends, retry classification/bounds and late
  finalization protection.
- [x] 4.3 Cover callback signature rejection, monotonic/idempotent transitions
  and static module/transaction boundaries.

## 5. Validation

- [x] 5.1 Run the focused pytest command from `design.md` locally and record
  the complete output.
- [x] 5.2 Run Ruff and `compileall` locally and record the complete output,
  distinguishing known pre-existing findings from regressions.
- [x] 5.3 Run `openspec validate add-twilio-outbound-delivery-5-6 --strict`
  and `git diff --check`; record exact outputs.

## 6. Review-blocker corrections (Phase-5.6)

- [x] 6.1 `MensajeProveedorSalienteRepository.claim_due` must select and
  claim exactly one due row per execution (PostgreSQL ``UPDATE ... WHERE id =
  (SELECT id ... ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *``)
  and recover rows in ``leased`` state whose ``lease_expira_en`` is in the
  past.
- [x] 6.2 `OutboundMessageDispatcher` must own the narrow claim transaction
  and the narrow finalize transaction; the Twilio network call must run with
  no SQLAlchemy session open. The dispatcher takes a ``session_factory``
  callable plus an ``outbox_repo_factory`` so production wires a real
  ``sessionmaker`` and tests can wire either a factory returning a mock or a
  real engine.
- [x] 6.3 `TwilioDeliveryCallbackService.apply_callback` must commit only on
  a successful monotonic ``applied`` transition; ``unknown``, ``duplicate``
  and ``regression`` outcomes must roll back without mutating the row. A
  technical failure inside the narrow transaction must roll back and
  propagate so the router surfaces it as a 5xx.
- [x] 6.4 `twilio_delivery_callback_adapter.extract_envelope` must raise
  `InvalidTwilioDeliveryCallbackForm` (not `InvalidTwilioInboundForm`) for a
  `MessageStatus` outside the closed set so the router returns ``204``
  without invoking the service or touching the database. Signature
  validation still returns ``403`` before any database access.
- [x] 6.5 Add real PostgreSQL focused tests that prove the lease and the
  callback transition survive a session close, that the network call runs
  outside the claim transaction, that two due rows yield exactly one claim
  while the other stays eligible, that an expired lease is recovered by the
  next claim, and that a signed callback with an unsupported ``MessageStatus``
  returns ``204`` without invoking the service or accessing the database.

## 7. Phase-5.6 production entry-point correction

- [x] 7.1 Add one minimal, explicit, manually invoked CLI entry point for
  outbound dispatch under `backend/cli/run_outbound_dispatch.py`. The CLI
  MUST build `OutboundMessageDispatcher` with the project's real
  `_SessionLocal` factory and the real
  `twilio.rest.Client(account_sid, auth_token).messages` seam, MUST call
  `run_retry_pass()` with a bounded explicit CLI argument
  (`--max-attempts-per-pass`, default `16`), MUST print only safe
  operational summaries (counts/outcomes and safe ids/SIDs), MUST fail
  non-zero when required outbound configuration is unavailable or when
  Twilio client construction / dispatch fails, and MUST preserve every
  Phase-5.6 boundary (no FastAPI endpoint, no background loop, no
  scheduler, no new transaction owner, no inbound pipeline invocation).
  The CLI exposes four injectable seams
  (`settings_loader`, `session_factory_builder`,
  `messages_client_builder`, `dispatcher_builder`) so focused tests
  can wire the real factory and the real Twilio messages client
  without monkey-patching the global `twilio.rest` module.
- [x] 7.2 Add the smallest necessary settings wiring required by the new
  CLI: `TWILIO_ACCOUNT_SID` on `Settings` with a canonical-format
  validator (must start with `AC`, 34 chars total, 32 hex chars after
  `AC`). Existing settings do not expose the account SID, and the
  Twilio REST client cannot be constructed without it. No other
  existing setting is changed.
- [x] 7.3 Add `backend/tests/test_run_outbound_dispatch_cli.py`
  covering, at minimum: the CLI builds the real dispatcher through the
  four injectable seams and wires `_SessionLocal` plus the real Twilio
  messages client; the bounded per-pass argument is forwarded to
  `run_retry_pass()` (default and explicit values); the summary
  renders only safe ids/SIDs (the auth token, the account SID, the
  outbound body and the inbound text never appear); missing /
  invalid configuration and a dispatch exception fail non-zero
  without leaking credentials or body bytes; the CLI performs zero
  network calls during testing. The CLI module imports `twilio.rest`
  lazily so module load never pulls in the Twilio SDK.
