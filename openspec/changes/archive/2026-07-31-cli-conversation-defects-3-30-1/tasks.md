## 1. CLI bootstrap creates and associates a draft Pedido

- [x] 1.1 Modify `backend/scripts/cli_chat_client.py`: replace the body of `_create_session` (or rename to `_bootstrap_session`) so it issues `POST /sessions`, then `POST /pedidos` with `{"id_session": <session_id>}`, then `PUT /sessions/{session_id}/pedido` with `{"id_pedido": <pedido_id>}` in that order. Hold the returned `pedido_id` in memory alongside `session_id`. Print `<session {session_id}>` and `<pedido {pedido_id}>` after the bootstrap completes.
- [x] 1.2 In the same file, extend the bootstrap error-handling branch so that a non-2xx response from `POST /pedidos` or `PUT /sessions/{id}/pedido` closes the session it created via `POST /sessions/{id}/cerrar` exactly once and exits non-zero with the API error detail on stderr.
- [x] 1.3 Add a new helper `_post_json_with_redirect` (or reuse `_post_json`) so the bootstrap can call `PUT` requests (the existing `_post_json` already supports `PUT` via the `data=` parameter and `method="POST"` constant — extend the helper to accept an optional `method` argument with a default of `"POST"` so the `PUT` call can be made).
- [x] 1.4 In `backend/tests/test_cli_chat_client.py`, update the bootstrap tests to assert the new three-call sequence and their ordering. Add a new test that asserts the bootstrap calls `POST /pedidos` with `{"id_session": <session_id>}` and `PUT /sessions/{session_id}/pedido` with `{"id_pedido": <pedido_id>}` exactly once each.
- [x] 1.5 In the same test module, add a test that asserts a `POST /pedidos` failure triggers a `POST /sessions/{id}/cerrar` cleanup and exits non-zero.
- [x] 1.6 In the same test module, add a test that asserts the exit handler still closes only the session it created (no pedido-close endpoint is called, no extra `/pedidos` `/pedido` calls beyond the bootstrap).

## 2. Pending-context execution clears context on rejected

- [x] 2.1 Modify `backend/intents/orchestration/pending_context_execution.py`: change the success branch from `if result.status == "executed":` to `if result.status in ("executed", "rejected"):` so the function calls `clear_pending_context(session)` and sets `session.context_type = None` for both executed and rejected outcomes.
- [x] 2.2 Confirm that the raised-exception contract is unchanged: any exception raised by the handler (after being wrapped by the handler itself into a `failed` `ProcessedIntent`, or escaping the handler) propagates out of `execute_ready_pending_context` unchanged. The transactional wrapper at `process_incoming_message_transactional` is the sole owner of `db.commit()` / `db.rollback()`.
- [x] 2.3 In `backend/tests/test_pending_context_execution.py`, add a test that asserts a `rejected` handler result triggers `clear_pending_context(session)` exactly once and sets `session.context_type = None` exactly once.
- [x] 2.4 In the same test module, add a test that asserts a `failed` handler result does NOT call `clear_pending_context(session)` and does NOT assign `session.context_type` (preserves the existing pre-3.30.1 behavior of failed).
- [x] 2.5 In the same test module, add a test that asserts a `rejected` outcome followed by a next unrelated message reaches `dispatch_initial_message` (not `dispatch_pending_context`) — i.e. the next message is re-classified from scratch.
- [x] 2.6 In the same test module, add a test that asserts a raised exception propagates out unchanged, `clear_pending_context` is not called, and `session.context_type` is not modified.

## 3. Product-selection resolver narrows candidate_ids

- [x] 3.1 Modify `backend/intents/context/product_selection_context_resolver.py`: add a new branch that fires when `len(resultado["encontrados"]) == 0` AND `resultado["encontrados_posibles"]` is non-empty. Compute the intersection of `active_intent.candidate_ids` with the `producto_presentacion_id`s extracted from the candidate groups (each group has a `productos` list of `{producto_presentacion_id, ...}` dicts).
- [x] 3.2 In the new branch, return the input unchanged when the intersection is empty (no infinite narrowing).
- [x] 3.3 In the new branch, when the intersection has exactly one element, reuse the existing unique-selection path: build a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the remaining id, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved in `resolved_data`, and `status == "ready"` when all required requirements are completed.
- [x] 3.4 In the new branch, when the intersection has more than one element, return a new `ProcessedIntent` whose `candidate_ids` is the intersection (preserving original order) and whose `status` stays `pending_resolution`. The other fields (`resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, `handler`) are preserved verbatim from the input.
- [x] 3.5 Confirm that the existing unique-selection branch (one item in `encontrados`) takes priority over the new narrowing branch. The narrowing branch only fires when `encontrados` is empty.
- [x] 3.6 In `backend/tests/test_product_selection_context_resolver.py`, add a test that asserts the five-pizza narrowing case: `candidate_ids == [5 ids]` and `message == "la grande"` returns an intent whose `candidate_ids == [3 large ids]` and `status == "pending_resolution"`.
- [x] 3.7 In the same test module, add a test that asserts the single-candidate narrowing case: `candidate_ids == [3 large ids]` and `message == "Pizza de Muzzarella Grande"` returns an intent with `resolved_data["producto_presentacion_id"]` set, `candidate_ids == []`, and `status == "ready"`.
- [x] 3.8 In the same test module, add a test that asserts the empty intersection returns the input unchanged (same instance).
- [x] 3.9 In the same test module, add a test that asserts the narrowing branch does not call `db.commit`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin` and does not mutate the input `active_intent` instance.

## 4. Regression test coverage for the full conversation

- [x] 4.1 Create `backend/tests/test_cli_conversation_regression.py` with the same `engine` / `TestingSessionLocal` pattern as `backend/tests/test_incoming_message_integration.py`. Define a `_seed_five_pizza_catalog(db)` helper that creates a comercio, cliente, categoria, producto, and five `ProductoPresentacion` rows (PizzaMuzzarellaChica, PizzaMuzzarellaGrande, PizzaNapolitanaChica, PizzaNapolitanaGrande, PizzaMargheritaGrande) with prices seeded from the existing catalog or local fixture values. The helper returns the ids and the active `Session` ORM instance.
- [x] 4.2 In the same test module, define a `_cleanup(db, ...)` helper that deletes the seeded rows in FK-safe order and runs inside `with db.begin():`. Each test wraps its body in `try/finally` so cleanup runs on failure.
- [x] 4.3 In the same test module, add a `test_full_conversation_executes_without_extra_turn` that runs the five-message flow: `quiero dos pizzas` (asserts five candidates), `la grande` (asserts three large candidates), `Pizza de Muzzarella Grande` (asserts `executed` and one `PedidoProducto` row with `cantidad == 2` and the seeded `precio_unitario`). The test patches `input()` to feed the three messages plus `exit`, patches `urllib.request.urlopen` to talk to the real running API on `http://127.0.0.1:8000` (or wraps the in-process FastAPI client), and asserts the CLI's printed output.
- [x] 4.4 In the same test module, add a `test_exact_unique_candidate_executes_in_same_turn` that types one refinement message containing the exact unique product name and asserts the response is `executed` (no confirmation prompt).
- [x] 4.5 In the same test module, add a `test_rejected_clears_pending_context` that forces a `rejected` handler outcome (e.g. by removing the `Producto` row before the refinement arrives) and asserts the next message's response is re-classified by `IntentClassifier` (context_type is `None`).
- [x] 4.6 In the same test module, add a `test_raised_exception_propagates_and_rolls_back` that monkey-patches `PedidoProductoService.add` to raise `IntegrityError`, asserts the exception propagates out of `process_incoming_message_transactional`, and asserts no `PedidoProducto` row was inserted.
- [x] 4.7 In the same test module, add a `test_cli_cleanup_closes_only_session` that drives the CLI to `exit` after a successful bootstrap and asserts the CLI issued `POST /sessions/{id}/cerrar` exactly once and no other session/pedido mutation endpoints.

## 5. Verification

- [x] 5.1 Run `PYTHONPATH=. venv/bin/python -m compileall backend` — must exit 0.
- [x] 5.2 Run `PYTHONPATH=. venv/bin/python backend/tests/test_cli_chat_client.py` — all CLI unit tests pass (old + new bootstrap tests).
- [x] 5.3 Run `PYTHONPATH=. venv/bin/python backend/tests/test_pending_context_execution.py` — all bounded-context execution tests pass (old + new rejected-clears tests).
- [x] 5.4 Run `PYTHONPATH=. venv/bin/python backend/tests/test_product_selection_context_resolver.py` — all resolver tests pass (old + new narrowing tests).
- [x] 5.5 Run `PYTHONPATH=. venv/bin/python backend/tests/test_cli_conversation_regression.py` — all five regression scenarios pass against `supernova_test`.
- [x] 5.6 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` — full smoke suite passes (the new tests do not break the existing 400+ tests).
- [x] 5.7 Run `openspec validate cli-conversation-defects-3-30-1 --strict` — change is valid.
- [x] 5.8 Sync the three delta specs to `openspec/specs/incoming-messages-interactive-cli/spec.md`, `openspec/specs/pending-context-execution/spec.md`, and `openspec/specs/product-selection-context-resolver/spec.md` (add the `## ADDED Requirements` blocks from this change's three spec files).
- [x] 5.9 Archive the change with `openspec archive cli-conversation-defects-3-30-1` once all of the above passes.
