## Why

The modern intents pipeline already ships two orchestration entry points — `dispatch_initial_message` (Subphase 3.23) for fresh messages that need classification, and `dispatch_pending_context` (Subphase 3.18) for messages that belong to an active product-selection context — but no module decides which one to call. Callers today would need to branch on `session.context_type` themselves and call the right dispatcher, duplicating the routing rule in every future consumer (FastAPI dependency, background worker, tests). Subphase 3.24 introduces the single internal entry point that owns that routing rule so the modern pipeline has one obvious front door.

## What Changes

- Add `backend/intents/orchestration/incoming_message_orchestrator.py` exporting `process_incoming_message(db, session, message: str) -> list[ProcessedIntent]`.
- Validate `message` is a non-empty string before any dispatch call; raise `TypeError` for non-string input and `ValueError` for empty / whitespace-only input.
- Route to `dispatch_pending_context` when `session.context_type` is set; wrap its `ProcessedIntent` return in a one-item list and return it without invoking `IntentClassifier` or `dispatch_initial_message`.
- Route to `dispatch_initial_message` when `session.context_type is None`; return its `list[ProcessedIntent]` unchanged, preserving the order produced by the classifier.
- Reuse the existing dispatchers verbatim — no SQLAlchemy queries, no repositories, no `commit`/`rollback`, no HTTP/Twilio/response logic, no handler implementation, no queue promotion.
- Add focused unit tests in `backend/tests/test_incoming_message_orchestrator.py` with stub dispatchers (no real LLM call, no database access, no orchestrator side-effects). Cover the two routing branches, message validation, the wrapping behavior, the order-preservation behavior, and the no-commit guarantee.

## Capabilities

### New Capabilities

- `incoming-message-orchestrator`: Defines the unified internal entry point `process_incoming_message` that routes every inbound message to either `dispatch_pending_context` (when a pending context is active) or `dispatch_initial_message` (when no pending context is active), validates the message, and preserves the result shape (`list[ProcessedIntent]`) for both branches.

### Modified Capabilities

- `initial-intent-dispatcher`: No requirement changes; remains the authoritative modern entry point for fresh messages. `process_incoming_message` is a consumer of `dispatch_initial_message` and introduces no new behavior on that side.
- `pending-context-dispatcher`: No requirement changes; remains the authoritative dispatcher for messages that arrive while a pending context is active. `process_incoming_message` is a consumer of `dispatch_pending_context` and introduces no new behavior on that side.
- `intent-classifier`: No requirement changes; prompts, catalog, logging, and constructor remain untouched. The classifier is only ever reached through `dispatch_initial_message`.

## Impact

- New module `backend/intents/orchestration/incoming_message_orchestrator.py` (sibling of `agregar_producto_orchestrator.py`, `initial_intent_dispatcher.py`, and `pending_context_dispatcher.py`).
- New tests `backend/tests/test_incoming_message_orchestrator.py` with stub `dispatch_initial_message` and stub `dispatch_pending_context`; no real LLM call, no `supernova_test` connection, no commit/rollback.
- Reused unchanged: `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/schemas/processed_intent.py`, `backend/models/session.py`, `backend/llm/intent_classifier.py`.
- Not touched: `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, recognizer, resolver, processor, handler, services, repositories, routers, dependencies, models, migrations, configuration, FastAPI dependency, Twilio integration, queue promotion.
- No new intents, no catalog changes, no prompt changes, no `QueryLlm` interaction beyond what `dispatch_initial_message` already performs.
- Routing logic between initial and pending dispatch is owned solely by `process_incoming_message`; downstream consumers should call this single entry point and stop branching on `session.context_type` themselves.
