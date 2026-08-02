## Why

The modern intents pipeline introduced by Subphase 3.24 exposes `process_incoming_message(db, session, message)` as the single internal front door for any inbound message, but the orchestrator deliberately leaves persistence to the caller: it validates the message, routes to `dispatch_pending_context` or `dispatch_initial_message`, and returns the resulting `list[ProcessedIntent]` without ever calling `db.commit()` or `db.rollback()`. Every future consumer (FastAPI dependency, background worker, Twilio webhook adapter, test harness) would therefore have to remember to wrap the call in a try/except, call `db.commit()` on success, and call `db.rollback()` on failure. Subphase 3.26 introduces the single transactional entry point that owns that commit/rollback boundary so every modern consumer of the intents pipeline shares one obvious transactional wrapper.

## What Changes

- Add `backend/intents/orchestration/transactional_message_processor.py` exporting `process_incoming_message_transactional(db, session, message) -> list[ProcessedIntent]`.
- Call `process_incoming_message(db, session, message)` once; on success call `db.commit()` exactly once and return the result; on any raised exception call `db.rollback()` exactly once and re-raise the original exception unchanged.
- Treat `rejected` and `failed` results as valid business outcomes — the function still commits when the inner orchestrator returns without raising.
- Reuse the existing `process_incoming_message` orchestrator verbatim — no SQLAlchemy queries, no repository access, no `HTTPException` translation, no response generation, no Twilio integration, no retry/backoff logic.
- Add focused unit tests in `backend/tests/test_transactional_message_processor.py` that mock `process_incoming_message` only (no real LLM call, no real database flow, no orchestrator side-effects). Cover the success path, the `rejected` / `failed` business-outcome commit, the exception path, and the original-exception re-raise.

## Capabilities

### New Capabilities

- `incoming-message-transactional-processor`: Defines the transactional wrapper `process_incoming_message_transactional` that delegates to `process_incoming_message`, commits exactly once on success (including for `rejected` / `failed` outcomes), rolls back exactly once on any exception, and re-raises the original exception unchanged. Owns the commit/rollback boundary so every consumer of the modern intents pipeline shares a single obvious transactional entry point.

### Modified Capabilities

- `incoming-message-orchestrator`: No requirement changes; remains the authoritative modern entry point that validates messages and routes between `dispatch_pending_context` and `dispatch_initial_message` without calling `commit()`/`rollback()`. `process_incoming_message_transactional` is a consumer of `process_incoming_message` and introduces no new behavior on that side.

## Impact

- New module `backend/intents/orchestration/transactional_message_processor.py` (sibling of `incoming_message_orchestrator.py`, `initial_intent_dispatcher.py`, and `pending_context_dispatcher.py`).
- New tests `backend/tests/test_transactional_message_processor.py` that mock `process_incoming_message` at the new module's import site with `MagicMock` returns; no real LLM call, no `supernova_test` connection, no commit/rollback against a real database.
- Reused unchanged: `backend/intents/orchestration/incoming_message_orchestrator.py`, `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/schemas/processed_intent.py`, `backend/models/session.py`.
- Not touched: `process_incoming_message`, `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, `QueryLlm`, recognizers, resolvers, processors, handlers, services, repositories, routers, dependencies, configuration, models, migrations, FastAPI dependencies, Twilio integration, queue promotion.
- The commit/rollback boundary is owned solely by `process_incoming_message_transactional`; downstream consumers should call this single entry point and stop wrapping `process_incoming_message` in try/except themselves.
