## 1. Confirmed local-status gate

- [x] 1.1 Preserve the existing exact `borrador` local-test path and introduce
  a separate exact-target eligibility branch for confirmed-or-later orders.
- [x] 1.2 For a clean confirmed target, classify once and allow only exactly
  one `consultar_estado_pedido`; fail closed for every other result, multiple
  intents, classifier failure, or pending context.
- [x] 1.3 Reuse the existing read-only status orchestration, shared response
  mapper, and exact safe snapshot projection; do not invoke the normal message
  processor in this branch.

## 2. Regression coverage

- [x] 2.1 Add focused route tests for flexible classifier-derived status,
  draft-path preservation, non-status/multi-intent rejection, and failure
  privacy.
- [x] 2.2 Prove exact-target isolation, clean-context gating, no session/order
  replacement, no business mutation, no transaction-control calls, and no
  provider/outbox/worker/Twilio activity on the confirmed path.

## 3. Validation

- [x] 3.1 Run the focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check` commands from `proposal.md`.
- [ ] 3.2 Run the post-deploy pilot gate: confirm an order in the local panel,
  ask at least two naturally phrased status questions, and verify the exact
  selected order remains unchanged; verify one add/new-order phrase is rejected
  without creating a successor session or altering the confirmed order.
