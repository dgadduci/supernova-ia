# Tasks

## 1. Pending recovery and read-only interruption

- [x] 1.1 Add the closed deterministic status predicate and route it before a
  supported pending resolver, preserving pending state exactly.
- [x] 1.2 Clear active pending state and `context_type` on a definitive
  resolver-produced rejection; preserve `pending_resolution` and technical
  failure behavior.
- [x] 1.3 Align the static status classifier wording and controlled corpus for
  the normal no-context path.

## 2. Privacy-safe structured tracing

- [x] 2.1 Extend the existing operational event catalogue and public exports
  with the closed `pending_context_transition` contract only.
- [x] 2.2 Emit allowlisted transition events without PII and make emission
  failure observational only.

## 3. Focused verification

- [x] 3.1 Add end-to-end coverage for Mozzarella ambiguity → `Grande` → add,
  rejected-context cleanup, and status during/after pending context.
- [x] 3.2 Add predicate, prompt/corpus, event privacy/parse and bounded query
  CLI tests.
- [x] 3.3 Run every focused pytest, Ruff, compileall, and strict OpenSpec
  validation command from `proposal.md` locally; report complete output.

## 4. Production gate and dependent change

- [x] 4.1 After `fix-pilot-product-add-execution` is approved,
  implemented, deployed and has passed its catalog/WhatsApp gate, run the three controlled
  WhatsApp message sequences in `proposal.md`; record only outcomes and
  timestamps, never customer content or identifiers.
- [ ] 4.2 Resume `implement-product-line-observation-intent` only after 4.1
  succeeds; test it in production with messages.
- [ ] 4.3 Obtain explicit user approval before archiving the observation
  change. Do not archive this change as an implied consequence of its tests.

## 5. Regression amendment — invalid pending state recovery

- [x] 5.1 In `dispatch_pending_context`, treat the following shapes as
  inconsistent and recover them without invoking the classifier, resolver,
  LLM, product handler, catalog or transaction-control methods:
  - `state.active is None` while `session.context_type` is non-null;
  - active present with `session.context_type is None`;
  - active present with `session.context_type` outside the supported
    context-kind allowlist.
  For each shape, clear the pending state, set `session.context_type = None`
  within the caller-owned transaction, return exactly one `rejected`
  outcome and let the next normal message reach initial dispatch.
- [x] 5.2 Extend only the `pending_context_transition` event with the closed
  `invalid_state_cleared` outcome. Allow `context_kind` to be any existing
  supported kind or the closed sentinels `none` and `unsupported`; allow
  `status_before` to be any existing status or the closed sentinel `none`;
  require `status_after` to remain `rejected`. The event MUST record
  zero candidate counts after the cleanup and `context_cleared=true`, and
  MUST NOT contain text, IDs, names, labels, prices, customer, pedido,
  session, exception material, correlation identifiers or free-form
  fields. Emission stays best-effort and never changes the customer flow.
- [x] 5.3 Add focused tests covering each invalid-state shape: cleanup of
  pending state, exactly one `rejected` return, no prohibited call (no
  classifier / resolver / LLM / product handler / catalog / transaction
  control), exactly one closed `pending_context_transition` event with
  `outcome=invalid_state_cleared`, and the subsequent message reaching
  initial dispatch.
- [x] 5.4 Strengthen the real `ProviderInboundMessageCoordinator` E2E
  test with two receipts and two leases: the first turn opens the Mozzarella
  ambiguity and stages the outgoing clarification; before the second turn,
  verify the durable `product_selection` state and exactly the two
  restricted candidates; `Grande` with a present price MUST produce one
  line, clear context/pending and generate a successful confirmation;
  explicitly assert the second outgoing message is NOT the
  "No pude procesar tu pedido…" rejection; verify the closed
  `pending_context_transition` and `product_add_execution` events are
  emitted.
- [ ] 5.5 (deferred) — DEFER until 5.1–5.4 ship and pass local validation;
  measure latency impact of the closed-event emission under realistic
  load before deciding whether to keep the `invalid_state_cleared` event
  on every invalid-state turn or downgrade it to a sampling variant.

## 6. Regression amendment — default quantity completion

- [x] 6.1 Make the existing `agregar_producto` contract default quantity `1`
  completed at initial intent construction when recognition omits quantity;
  preserve explicit valid quantities and current invalid/technical behavior.
- [x] 6.2 Add focused processor and restricted product-selection coverage for
  two persisted candidates with no quantity: `Grande` must become `ready`,
  execute one default-quantity add and clear context without candidate
  widening or LLM authority.
- [x] 6.3 Strengthen provider-coordinator E2E across two receipts/leases with
  a first-turn hybrid-style ambiguous result that omits quantity; assert the
  durable default before selection, success outbound response and closed
  pending/product-add events after selection. Update the directly affected
  legacy smoke expectation.
- [x] 6.4 Run the focused pytest, Ruff, compileall and strict OpenSpec
  validation commands in `proposal.md` locally; report complete output.
- [ ] 6.5 After approved deploy, repeat the controlled ambiguity → `Grande`
  WhatsApp sequence with a new clean session/pedido and verify one successful
  response and line in the pilot panel. Only then resume gates 4.1–4.3; do not
  archive any active change.
