## 1. Approval and readiness

- [x] 1.1 Review and approve this operational pilot boundary; name the single
  commerce and designated internal test numbers outside the repository.
- [x] 1.2 Review the existing Railway runbook and confirm its required
  configuration/readiness evidence without exposing secrets.
- [x] 1.3 Approve the bounded routing-provisioning design: internal CLI only,
  default read-only verification, explicit apply, one setup transaction,
  sanitized output, and no direct SQL/API route.

## 2. Routing provisioning implementation

- [x] 2.1 Implement the approved CLI and its small service/repository staging
  boundary without changing webhook, recognition, outbox, scheduler, schema
  or migrations.
- [x] 2.2 Cover ready, missing client/channel, explicit reactivation,
  conflicting/inactive channel, failed commerce validation, rollback and
  sanitized-output cases with focused tests.
- [x] 2.3 Run and report the focused pytest, Ruff, compileall, strict
  OpenSpec validation and `git diff --check` commands in `design.md`.

## 3. Local manual verification

- [x] 3.1 Run the focused local validation commands in `design.md` and share
  complete output for review.
- [x] 3.2 Run the CLI happy-path and ambiguity-path cases with `--debug-flow`;
  record sanitized evidence only.

## 4. Controlled WhatsApp verification

- [x] 4.1 Verify Railway revision, Alembic head, public health and the
  integrated Ollama generate/embed probes using the existing runbook.
- [x] 4.2 Run the routing CLI in verification mode. If and only if it reports
  not-ready, run the approved explicit apply mode once and re-run verification;
  retain sanitized IDs/statuses only.
- [x] 4.3 Configure/confirm Twilio routes and send one controlled inbound
  WhatsApp case from a designated test number only after routing verification
  reports ready.
- [x] 4.4 Invoke exactly one bounded inbound-processing pass and one bounded
  outbound-dispatch pass; record safe counters/IDs and inspect the signed
  callback state.
- [x] 4.5 Retain the focused receipt-idempotency evidence; no additional live
  duplicate-receipt or retry case was needed, so no bulk traffic was sent.

## 5. Review and next decision

- [x] 5.1 Classify every case against the manual acceptance matrix and review
  all reported evidence.
- [x] 5.2 Recommend either a narrow remediation change, continued pilot, or a
  proposal for order confirmation/payment/delivery closure. Do not implement
  any of those outcomes in this change.
