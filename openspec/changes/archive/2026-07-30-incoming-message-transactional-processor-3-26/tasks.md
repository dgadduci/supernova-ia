## 1. Transactional Processor Implementation

- [x] 1.1 Create `backend/intents/orchestration/transactional_message_processor.py` with `__all__ = ["process_incoming_message_transactional"]` and the documented imports: `Session as DatabaseSession` from `sqlalchemy.orm`, `Session as ConversationSession` from `backend.models.session`, `ProcessedIntent` from `backend.intents.schemas.processed_intent`, and `process_incoming_message` from `backend.intents.orchestration.incoming_message_orchestrator`.
- [x] 1.2 Implement `process_incoming_message_transactional(db, session, message)` so it calls `process_incoming_message(db, session, message)` exactly once inside `try:`; on success fall through to `db.commit()` and `return result`; on any exception execute `db.rollback()` and bare `raise` to re-raise the original exception unchanged.
- [x] 1.3 Do not introduce logging, retry/backoff, caching, async wrappers, response shaping, `HTTPException` translation, savepoints, nested transactions, `db.flush`, `db.refresh`, or `db.expire` inside the wrapper.
- [x] 1.4 Do not import from `backend/old_project/`, `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, or any handler / queue / response-shaping module.

## 2. Boundaries

- [x] 2.1 Keep the wrapper free of SQLAlchemy `select` / `execute` / `add` / `delete`, repository imports, router imports, and `backend.sessions` imports.
- [x] 2.2 Do not call `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; only `db.commit()` (success path) and `db.rollback()` (exception path) are allowed.
- [x] 2.3 Do not modify `backend/intents/orchestration/incoming_message_orchestrator.py`, `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/intents/schemas/processed_intent.py`, `backend/intents/schemas/intent_classification.py`, `backend/llm/intent_classifier.py`, `backend/llm/query_llm.py`, or `backend/models/session.py`.
- [x] 2.4 Do not import anything from `backend/old_project/`.

## 3. Verification

- [x] 3.1 Add `backend/tests/test_transactional_message_processor.py` with a stubbed `process_incoming_message`: patch `process_incoming_message` at the new module's import site (`backend.intents.orchestration.transactional_message_processor.process_incoming_message`) with `MagicMock` returning sentinel values. Use `unittest.TestCase` style consistent with `backend/tests/test_incoming_message_orchestrator.py`. Pass a `MagicMock(name="DatabaseSession")` as `db` and a `MagicMock(name="ConversationSession")` as `session`.
- [x] 3.2 Cover the success path: stub `process_incoming_message` to return a sentinel `list[ProcessedIntent]`; assert `process_incoming_message` was called exactly once with `(db, session, message)`, `db.commit` was called exactly once, `db.rollback` was NOT called, and the returned list is the same list reference the stub produced.
- [x] 3.3 Cover the `rejected` business-outcome path: stub `process_incoming_message` to return a one-item list whose `ProcessedIntent.status == "rejected"`; assert `db.commit` was called exactly once, `db.rollback` was NOT called, and the list was returned to the caller.
- [x] 3.4 Cover the `failed` business-outcome path: stub `process_incoming_message` to return a one-item list whose `ProcessedIntent.status == "failed"`; assert `db.commit` was called exactly once, `db.rollback` was NOT called, and the list was returned to the caller.
- [x] 3.5 Cover the mixed-status list path: stub `process_incoming_message` to return a multi-item list mixing `executed`, `rejected`, and `failed` items; assert `db.commit` was called exactly once, `db.rollback` was NOT called, and the full list was returned to the caller.
- [x] 3.6 Cover the exception path: stub `process_incoming_message` to raise a sentinel exception (e.g., a custom `RuntimeError`); use `self.assertRaises(RuntimeError)` and assert `db.rollback` was called exactly once, `db.commit` was NOT called, and the raised exception is the exact same instance the stub produced (identity check on the raised object).
- [x] 3.7 Cover exception-type preservation across multiple exception types: stub `process_incoming_message` to raise `ValueError`, `TypeError`, and a `QueryLlmError`-shaped exception in separate tests; for each, assert `db.rollback` was called exactly once, `db.commit` was NOT called, and `process_incoming_message_transactional` re-raises the same type (and same instance) unchanged (no wrapping, no conversion to `HTTPException`).
- [x] 3.8 Cover the no-other-database-calls guarantee: pass a `MagicMock(name="DatabaseSession")` as `db`; after both the success and exception tests, assert `db.flush.assert_not_called()`, `db.refresh.assert_not_called()`, `db.expire.assert_not_called()`, and `db.begin.assert_not_called()`.
- [x] 3.9 Cover `__all__` discipline: import the module and assert `module.__all__ == ["process_incoming_message_transactional"]`.
- [x] 3.10 Run `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_transactional_message_processor` and confirm all tests pass without a real LLM call, without a real `supernova_test` connection, and without any network access.
- [x] 3.11 Run `PYTHONPATH=. venv/bin/python -m compileall backend` and confirm exit 0.
- [x] 3.12 Run `openspec validate incoming-message-transactional-processor-3-26 --strict` and confirm valid.
