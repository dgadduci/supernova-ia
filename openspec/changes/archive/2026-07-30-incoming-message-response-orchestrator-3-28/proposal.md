## Why

The modern intents pipeline (Subphases 3.24 → 3.27) now delivers `process_incoming_message_transactional` returning a `list[ProcessedIntent]` and `build_agregar_producto_response` converting one such intent into a `CustomerResponse`. There is still no seam that ties the two together: callers that want both the transactional boundary and the customer-facing strings must hand-roll a loop, replicate the per-intent routing rule, and decide how to handle unsupported intents. Without this seam the pipeline is complete at the intent layer but unreachable from the customer surface that Twilio / FastAPI adapters will eventually own.

## What Changes

- Add `backend/intents/orchestration/incoming_message_response_orchestrator.py` exposing `process_incoming_message_with_responses(db: DatabaseSession, session: ConversationSession, message: str) -> list[CustomerResponse]` through `__all__`.
- Use the typed-alias convention: `sqlalchemy.orm.Session as DatabaseSession` and `backend.models.session.Session as ConversationSession`.
- Reuse `process_incoming_message_transactional(db, session, message)` exactly once per invocation; do not duplicate the validation, routing, or commit / rollback rules.
- Preserve the order of the returned `ProcessedIntent` list.
- For each `ProcessedIntent`, dispatch by `intent.intent`:
  - `intent == "agregar_producto"`: call `build_agregar_producto_response(db, session, intent)` and append the returned `CustomerResponse`.
  - any other `intent` (incl. `desconocida`, `saludo`, `quitar_producto`, etc.): append a deterministic generic `CustomerResponse(message=GENERIC_MESSAGE, intent=<intent>, status=<status>)` that preserves the original `intent` and `status`.
- Return one `CustomerResponse` per processed intent; the returned list length equals the inner list length.
- Do not call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; transaction ownership remains with `process_incoming_message_transactional`.
- Do not introduce logging, retry / backoff, async wrappers, caching, locale selection, template engines, response beautification, Twilio / FastAPI integration, or response objects for new intents.
- Keep the module free of SQLAlchemy queries, repository access, LLM calls, HTTP, Twilio, `backend.routers`, `backend.sessions`, `backend.dependencies`, `backend.llm`, `backend.old_project`, recognizers, resolvers, processors, handlers, services, context, and queue modules.
- Add focused tests in `backend/tests/test_incoming_message_response_orchestrator.py` that mock `process_incoming_message_transactional` and `build_agregar_producto_response` to lock the per-intent routing, order preservation, exception propagation, and absence of new commit / rollback calls.

## Capabilities

### New Capabilities

- `incoming-message-response-orchestrator`: Defines the modern seam that processes an inbound message transactionally and converts the resulting `list[ProcessedIntent]` into a `list[CustomerResponse]`. Covers the orchestrator signature, the single delegation to `process_incoming_message_transactional`, the per-`intent.intent` dispatch (delegating `agregar_producto` to `build_agregar_producto_response`, returning a deterministic generic `CustomerResponse` for every other intent while preserving the original `intent` and `status`), order preservation, exception propagation unchanged, and the boundaries that keep this layer free of SQLAlchemy queries, repository access, LLM calls, HTTP / Twilio integration, new commit / rollback calls, logging, retries, async wrappers, response beautification, and response objects for additional intents.

### Modified Capabilities

## Impact

- New files: `backend/intents/orchestration/incoming_message_response_orchestrator.py`, `backend/tests/test_incoming_message_response_orchestrator.py`.
- Reused unchanged: `backend/intents/orchestration/transactional_message_processor.py` (`process_incoming_message_transactional`), `backend/intents/orchestration/incoming_message_orchestrator.py` (`process_incoming_message`), `backend/intents/responses/agregar_producto_response.py` (`build_agregar_producto_response`), `backend/intents/schemas/customer_response.py` (`CustomerResponse`), `backend/intents/schemas/processed_intent.py` (`ProcessedIntent`), `backend/models/session.py`.
- Not touched: `backend/intents/handlers/*`, `backend/intents/context/*`, `backend/intents/orchestration/{initial_intent_dispatcher,pending_context_dispatcher,pending_context_execution,agregar_producto_orchestrator}.py`, `backend/intents/recognizers/*`, `backend/intents/resolvers/*`, `backend/intents/processor.py`, `backend/intents/contracts/*`, `backend/services/*`, `backend/repositories/*`, `backend/llm/*`, `backend/routers/*`, `backend/dependencies.py`, `backend/main.py`, models, migrations, configuration.
- Not introduced: SQLAlchemy queries, repository access, LLM calls, new commit / rollback, `flush` / `refresh` / `expire` / `begin`, HTTP / Twilio integration, response objects for additional intents, response beautification, locale selection, logging, retry / backoff, async wrappers, queue promotion, queue / handler / dispatcher imports, or imports from `backend.old_project`.