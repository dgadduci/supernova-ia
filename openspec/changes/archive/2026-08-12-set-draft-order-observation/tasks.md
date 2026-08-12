# Tasks

## 1. Specification and approval

- [x] 1.1 Verify the inbound execution path, the existing draft-closure
  pipeline, the `Pedido`/`PedidoProducto` models, the migration
  history, and the shared response/outbox mapper.
- [x] 1.2 Confirm `set_observacion_pedido` is in the `IntentName`
  enum and the classifier contract but has no dispatcher branch,
  response builder, or persisted field on `pedidos`.
- [x] 1.3 Define authoritative outcomes, normalization rules, length
  range, isolation, fallback absence, transaction ownership,
  observability, validation commands, reversibility, and deferred
  limits.
- [x] 1.4 Obtain user approval before implementation.

## 2. Implementation (after approval)

- [ ] 2.1 Add a nullable `Text` `pedidos.observaciones` column on
  `Pedido` and a reversible Alembic migration (no backfill, no
  default, no index, no check constraint) chained from
  `7c4d5e6f7a8b`.
- [ ] 2.2 Add `process_initial_set_observacion_pedido` and the
  `_normalize_observacion` helper in
  `backend/intents/orchestration/draft_order_closure.py`, reusing
  the existing `_load_session_pedido` and `_rejected` helpers.
- [ ] 2.3 Add the `SET_OBSERVACION_PEDIDO` branch in
  `dispatch_initial_message` (`initial_intent_dispatcher.py`).
- [ ] 2.4 Add `build_set_observacion_pedido_response` in
  `backend/intents/responses/draft_order_closure.py` and the
  `elif` branch in
  `backend/services/outbound_response_mapper.py` `build_customer_responses`.
- [ ] 2.5 Add `backend/tests/test_draft_order_observation.py` with
  focused PostgreSQL-backed scenarios: NULL replacement, replacement
  of an existing value, Unicode whitespace collapse, 1..500 accept
  range, `text_empty` / `text_too_long` preservation, `no_draft` /
  `session_mismatch` / `pedido_not_borrador` non-mutation, dispatcher
  routing, local/outbox response equivalence, no-transaction-control
  proof, response safety (no raw text in `resolved_data` /
  `CustomerResponse.message` / outbox row), and migration reversibility.

## 3. Validation and handoff

- [ ] 3.1 User runs the exact focused pytest command from
  `proposal.md` locally and reports complete output.
- [ ] 3.2 User runs the exact Ruff and `compileall` commands from
  `proposal.md` locally and reports complete output.
- [ ] 3.3 User runs `openspec validate set-draft-order-observation
  --strict` locally and reports complete output.
- [ ] 3.4 Codex reviews changed scope, code, tests, static checks,
  migration reversibility, transaction ownership, isolation, and the
  complete local validation output.
- [ ] 3.5 User authorizes commit, sync, production deployment, and
  archive; no unrelated cleanup is performed.
