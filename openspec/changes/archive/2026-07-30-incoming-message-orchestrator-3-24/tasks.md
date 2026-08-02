## 1. Orchestrator Implementation

- [x] 1.1 Create `backend/intents/orchestration/incoming_message_orchestrator.py` with `__all__ = ["process_incoming_message"]` and the documented imports: `Session as DatabaseSession` from `sqlalchemy.orm`, `Session as ConversationSession` from `backend.models.session`, `ProcessedIntent` from `backend.intents.schemas.processed_intent`, `dispatch_initial_message` from `backend.intents.orchestration.initial_intent_dispatcher`, and `dispatch_pending_context` from `backend.intents.orchestration.pending_context_dispatcher`.
- [x] 1.2 Implement `process_incoming_message(db, session, message)` so that it validates `message` first: raise `TypeError` if `message` is not a `str`; raise `ValueError` if `not message.strip()` (covers empty and whitespace-only). Validation runs before any dispatcher call.
- [x] 1.3 Route to `dispatch_pending_context(db, session, message)` when `session.context_type is not None`; return `[dispatch_pending_context_result]` (wrap the single `ProcessedIntent` in a one-item list). Do NOT call `dispatch_initial_message` in this branch.
- [x] 1.4 Route to `dispatch_initial_message(db, session, message)` when `session.context_type is None`; return its `list[ProcessedIntent]` unchanged, preserving the order produced by the classifier. Do NOT mutate, filter, sort, or re-shape the returned list.
- [x] 1.5 Do not introduce logging, retry/backoff, caching, async wrappers, or response shaping inside the orchestrator.

## 2. Boundaries

- [x] 2.1 Keep the orchestrator free of `requests`, `fastapi`, `twilio`, `sqlalchemy.select`, repository imports, router imports, `backend.sessions` imports, and any handler / queue / response-shaping module imports.
- [x] 2.2 Do not call `db.commit`, `db.rollback`, or any other SQLAlchemy mutating method from the orchestrator.
- [x] 2.3 Do not modify `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/intents/schemas/processed_intent.py`, `backend/intents/schemas/intent_classification.py`, `backend/llm/intent_classifier.py`, `backend/llm/query_llm.py`, or `backend/models/session.py`.
- [x] 2.4 Do not import anything from `backend/old_project/`.

## 3. Verification

- [x] 3.1 Add `backend/tests/test_incoming_message_orchestrator.py` with stubs: patch `dispatch_initial_message` and `dispatch_pending_context` at the orchestrator's import site with `MagicMock` returning sentinel values. Use `unittest.TestCase` style consistent with `backend/tests/test_initial_intent_dispatcher.py`.
- [x] 3.2 Cover the initial branch: `session.context_type is None` → `dispatch_initial_message(db, session, message)` is called exactly once, `dispatch_pending_context` is NOT called, and the returned list is the dispatcher's list unchanged (identity-preserving or contents-preserving — assert contents and length).
- [x] 3.3 Cover the initial branch with a multi-item list: dispatcher returns `[intent_a, intent_b]`; the orchestrator returns the same two items in the same order.
- [x] 3.4 Cover the pending branch: `session.context_type == "product_selection"` (and a second test with any other non-`None` value) → `dispatch_pending_context(db, session, message)` is called exactly once, `dispatch_initial_message` is NOT called, and the returned list has length 1 containing exactly the dispatcher's `ProcessedIntent`.
- [x] 3.5 Cover pending-dispatcher error propagation: stub `dispatch_pending_context` to raise a sentinel exception; assert the orchestrator re-raises it unchanged (not wrapped, not converted, not swallowed).
- [x] 3.6 Cover initial-dispatcher error propagation: stub `dispatch_initial_message` to raise `TypeError`, `ValueError`, and a sentinel `QueryLlmError`-shaped exception in separate tests; assert each re-raises unchanged.
- [x] 3.7 Cover message validation: non-string input (`None`, `123`, list) raises `TypeError` before any dispatcher call; empty string raises `ValueError` before any dispatcher call; whitespace-only string (`"   "`, `"\n\t"`) raises `ValueError` before any dispatcher call. In each validation test, assert neither dispatcher is invoked.
- [x] 3.8 Cover the no-commit / no-rollback guarantee: pass a `MagicMock(name="DatabaseSession")` as `db`; after any routing branch completes, assert `db.commit.assert_not_called()` and `db.rollback.assert_not_called()`.
- [x] 3.9 Cover `__all__` discipline: import the module and assert `module.__all__ == ["process_incoming_message"]`.
- [x] 3.10 Run `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_incoming_message_orchestrator` and confirm all tests pass without a real LLM call, without a real `supernova_test` connection, and without any network access.
- [x] 3.11 Run `PYTHONPATH=. venv/bin/python -m compileall backend` and confirm exit 0.
- [x] 3.12 Run `openspec validate incoming-message-orchestrator-3-24 --strict` and confirm valid.
