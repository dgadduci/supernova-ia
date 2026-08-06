## 1. Receipt and core boundary

- [x] 1.1 Add the reversible provider-message receipt persistence model,
  restrictive foreign keys and provider/receipt uniqueness constraint.
- [x] 1.2 Add conflict-safe receipt claim/retrieval repository behavior.
- [x] 1.3 Define typed command and outcomes with safe observability fields.
- [x] 1.4 Implement routing-decision validation for dedicated and selected
  shared contexts without fallback.
- [x] 1.5 Revalidate an active `ComercioCanalCompartido` membership for the
  shared-channel authority path before claiming a receipt; a revoked or
  missing membership on the same channel returns `invalid_context` with
  no receipt, no session and no pipeline invocation.

## 2. Single transaction processing

- [x] 2.1 Extract/reuse a non-transactional pipeline primitive while retaining
  local endpoint behavior.
- [x] 2.2 Add caller-owned active-session staging; do not reuse committing
  `SessionService` operations from the provider coordinator.
- [x] 2.3 Implement the sole 5.4 transaction owner: claim, session, pipeline,
  exactly one commit; rollback and propagate technical failures.

## 3. Focused tests

- [x] 3.1 Cover first processing, duplicate idempotency and concurrent claim.
- [x] 3.2 Cover dedicated and selected-shared authority, plus invalid/pending
  shared contexts with no mutation.
- [x] 3.3 Cover rollback atomicity and static transaction/no-provider-boundary
  rules.
- [x] 3.4 Preserve local transactional processor and endpoint coverage.
- [x] 3.5 Cover shared selection with revoked `ComercioCanalCompartido`
  membership: returns `invalid_context` with `revoked_shared_membership`
  source and zero mutations (no receipt, no session, no pipeline call).
- [x] 3.6 Real-PostgreSQL integration tests for the receipt claim
  `INSERT ... ON CONFLICT DO NOTHING RETURNING` boundary: first claim
  inserts a row, duplicate claim returns `False` and never inserts a
  second row, and a rolled-back first attempt lets a later valid claim
  become the first committed row.

## 4. Validation

- [x] 4.1 Run focused pytest, Ruff and `compileall` on every touched file.
- [x] 4.2 Run strict OpenSpec validation and `git diff --check`.
- [x] 4.3 Record exact outputs and any pre-existing failures/blockers here.

### Focused validation outputs

- `pytest`:
  `116 passed, 85 subtests passed in 1.12s`
  (covers `backend/tests/test_provider_message_receipt_core.py`,
  `backend/tests/test_provider_message_receipt_core_integration.py`
  (new, real PostgreSQL),
  `backend/tests/test_transactional_message_processor.py`,
  `backend/tests/test_incoming_message_orchestrator.py`,
  `backend/tests/test_incoming_message_response_orchestrator.py`,
  `backend/tests/test_incoming_messages_endpoint.py`).
  Membership-revalidation coverage: focused
  `SharedChannelAuthorityTest
  .test_shared_selected_with_revoked_membership_returns_invalid_context`
  and integration
  `SharedChannelMembershipRevokedIntegrationTest
  .test_revoked_membership_yields_invalid_context_with_zero_mutations`
  and
  `test_missing_membership_yields_invalid_context_with_zero_mutations`.
- `ruff check backend/services/provider_inbound_message_coordinator.py
  backend/tests/test_provider_message_receipt_core.py
  backend/tests/test_provider_message_receipt_core_integration.py`:
  `All checks passed!`.
- `compileall -q backend/services/provider_inbound_message_coordinator.py
  backend/tests/test_provider_message_receipt_core.py
  backend/tests/test_provider_message_receipt_core_integration.py`:
  exit 0, no output.
- `openspec validate add-provider-message-receipt-core-5-4 --strict`:
  `Change 'add-provider-message-receipt-core-5-4' is valid`.
- `git diff --check`: clean (no output, exit 0).
- Alembic head after migration added:
  `head: f7a3b8c1d2e4`, single head. The new revision correctly
  down-revs from `e2f3a4b5c6d7` (the verified head captured at
  planning time).

## Deferred

- [ ] 5.5 signature-validated Twilio webhook/TwiML.
- [ ] 5.6 outbound delivery, callback states, retries and response replay.
