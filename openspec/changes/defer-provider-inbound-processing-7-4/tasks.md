## 1. Design completion and approval

- [x] 1.1 Confirm the bounded manual inbound processor is accepted for the
  pilot instead of an always-on worker.
- [x] 1.2 Confirm the named model/repository/coordinator/webhook/CLI boundary
  and exact validation commands before implementation approval.

## 2. Durable acceptance and processing

- [x] 2.1 Add the inbound-work persistence model, migration, repository and
  state/lease contracts with one work item per receipt.
- [x] 2.2 Refactor the provider boundary into short webhook acceptance and
  deferred processing without duplicating routing, idempotency, session/pedido,
  pipeline or outbound mapping rules.
- [x] 2.3 Add the explicit bounded inbound-processing CLI with sanitized output
  and no automatic loop.
- [x] 2.4 Clear transient message text on processed/terminal rows and preserve
  only safe operational fields.

## 3. Verification

- [x] 3.1 Cover acceptance latency boundary, duplicates, invalid context,
  durable work uniqueness, processor ordering, leases, retry, scrub and
  rollback with focused unit/integration tests.
- [x] 3.2 Validate upgrade against `supernova_test`; no downgrade or production
  data operation.
- [x] 3.3 Run every exact validation command and report complete output.

## 4. Operational boundary

- [x] 4.1 Do not deploy, dispatch production messages, add a worker/scheduler,
  sync, archive or perform direct Railway data repair in this change.

## 5. Conversational ordering fix

- [x] 5.1 Enforce the `(canal_id, cliente_id)` conversational block in
  `claim_due` via a correlated `NOT EXISTS` predicate so a later work item is
  never claimed while an earlier receipt in the same conversation has work in
  any non-terminal state (`pending`, `leased` or `retryable`). The
  conversational block is unconditional based on state and is independent of
  `lease_expira_en` and `proximo_intento_en`: a `retryable` blocker with a
  future `proximo_intento_en` and a `leased` blocker with an expired lease
  both remain blockers for a later candidate. Receipt creation order is
  `recepciones_mensajes_proveedor.fecha_recepcion` with
  `recepciones_mensajes_proveedor.id` as the stable tiebreaker; unrelated
  conversations remain independent; `processed` and `failed_terminal` rows
  never block. The candidate's own eligibility remains time-bounded so the
  documented retry budget is preserved: a `retryable` candidate is only
  claimable when its `proximo_intento_en` is due (or unset) and a `leased`
  candidate is only claimable through the lease-recovery path.
- [x] 5.2 Replace the previous `RetryOrderingIntegrationTest` (which only
  covered a future-due retryable) with three real PostgreSQL cases against
  `supernova_test`: retryable-due first blocks a pending later item and the
  same pass unblocks it after the first item reaches `processed`; the first
  item's `failed_terminal` unblocks the later item; an unrelated conversation
  progresses while the blocked conversation is still unresolved.
- [x] 5.3 Add real PostgreSQL cases against `supernova_test` that prove the
  unconditional conversational block: a `retryable` row with a future
  `proximo_intento_en` blocks a later pending row in the same conversation
  and unblocks it after the blocker reaches a terminal state; a `leased`
  row with an expired `lease_expira_en` still blocks a later pending row
  (while remaining eligible for its own lease-recovery claim) and unblocks
  it after the blocker reaches a terminal state.
