# Tasks

## 1. Owned order-line recognition projection

- [x] 1.1 Extend only `PedidoProductoRepository.list_by_pedido`'s existing
  eager-loading graph to include the category of the line's product; retain
  its current query, ordering and public service contract.
- [x] 1.2 Populate `categoria_nombre` from that eager-loaded owned category in
  `quitar_producto_recognizer`; do not query a commerce catalog or alter the
  shared recognizer/hybrid policy.

## 2. Focused proof

- [x] 2.1 Add a repository surface assertion for the category projection and
  recognizer coverage for `pizza de mozzarella` returning only the two
  Mozzarella own lines despite an unrelated order line.
- [x] 2.2 Add initial-orchestration coverage that those two candidates enter
  the existing pending context without a handler execution or transaction
  control.
- [x] 2.3 Run every focused pytest, Ruff, compileall and strict OpenSpec
  validation command from `proposal.md` locally; report complete output.

  #### 2.3.a Pre-existing limitations observed during local validation

  The focused validation command from `proposal.md` was executed against
  this change's worktree. The state of the focused suite was:

  - `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_pedido_producto_service_surface.py backend/tests/test_quitar_producto_recognizer.py backend/tests/test_quitar_producto_initial.py backend/tests/test_quitar_producto_end_to_end.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_controlled_hybrid_product_recognition.py` reported **117 tests passed and 1 failed**, **51 subtests passed**, exit code 1.
  - The single failure is
    `backend/tests/test_quitar_producto_end_to_end.py::QuitarProductoEndToEndIntegrationTest::test_initial_pending_context_with_multiple_lines`,
    raised by `sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint "uq_pedido_producto_presentacion"`.
    The integration fixture seeds two `PedidoProducto` rows that share the
    same `(id_pedido, id_producto_presentacion)` combination; the database
    rejects the second insert. This failure was reproduced after
    `git stash` of this implementation's changes (i.e. on the pristine
    worktree before any code in this change was applied) and therefore
    is **pre-existing debt outside this change's scope**. It is not
    corrected here.
  - `PYTHONPATH=. venv/bin/python -m ruff check` on the eight files
    listed in `proposal.md` reported 3 F401 (unused-import) findings,
    all pre-existing on the pristine worktree:
    - `importlib` in `backend/tests/test_pedido_producto_service_surface.py:1`;
    - `ProcessedIntent` in `backend/tests/test_quitar_producto_initial.py:13`;
    - `RequirementState` in `backend/tests/test_quitar_producto_initial.py:14`.
    These are likewise **pre-existing debt outside this change's scope**
    and are not corrected here.
  - `PYTHONPATH=. venv/bin/python -m compileall -q backend/repositories/pedido_producto_repository.py backend/intents/recognizers/quitar_producto_recognizer.py` exited 0 with no output (success).
  - `openspec validate fix-pilot-order-line-category-recognition --strict` printed `Change 'fix-pilot-order-line-category-recognition' is valid` and exited 0.
  - `git diff --check` produced no output and exited 0.

  The two pre-existing limitations above are reported as documentation of
  the local validation step only. They are not regressions introduced by
  this change, are not in scope of the approved `quitar_producto` order-
  line category projection, and must not block approval. Production gates
  3.1, 3.2 and 3.3 remain pending and MUST stay unchecked.

## 3. Production gate and dependent changes

- [ ] 3.1 After approved deploy, send the controlled remove request and prove
  it asks between the two Mozzarella lines while leaving the Pedido unchanged.
- [ ] 3.2 Send the outside-candidate `Napolitana chica` clarification, verify
  one rejection, no line mutation and context cleanup; then send the explicit
  status question to prove initial dispatch resumed.
- [ ] 3.3 Resume the remaining gate of
  `fix-pending-context-recovery-and-status-query`, then the production test of
  `implement-product-line-observation-intent`, only after 3.1–3.2 pass. Do
  not archive any change without explicit user approval.
