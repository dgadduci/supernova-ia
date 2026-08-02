## Why

The modern `agregar_producto` pipeline (Subphases 3.24 → 3.26) ends with `process_incoming_message_transactional` returning a `list[ProcessedIntent]`, but nothing translates those intents into a customer-facing reply. Every other modern layer (recognizer, resolver, processor, handler, dispatcher, transactional wrapper) is now defined, but the customer reply is the last missing seam — without it the pipeline cannot reach the customer. Subphase 3.27 introduces the deterministic response shaper for `agregar_producto` only, leaving Twilio / FastAPI transport integration and response beautification for future subphases.

## What Changes

- Add `backend/intents/schemas/customer_response.py` exposing a single `CustomerResponse` Pydantic model with three string fields: `message`, `intent`, `status`.
- Add `backend/intents/responses/agregar_producto_response.py` exposing `build_agregar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse`.
- Use the typed-alias convention: `sqlalchemy.orm.Session as DatabaseSession` and `backend.models.session.Session as ConversationSession`.
- Support only `intent.intent == "agregar_producto"`; return a generic apology response for any other intent.
- For `status == "pending_resolution"` with non-empty `candidate_ids`: load the candidate product-presentations through the existing `ProductoQueryService.list_presentaciones_by_ids` (no SQLAlchemy, no repository imports); build a concise clarification listing only the available presentation names (`"Pizza Mozzarella grande"`, `"Pizza Mozzarella chica"`) — no IDs, no prices, no debug text.
- For `status == "executed"`: load the resolved product-presentation through `ProductoQueryService.list_presentaciones_by_ids([resolved_data["producto_presentacion_id"]])`; confirm the product name, presentation name, and `cantidad` in a single deterministic sentence.
- For `status == "rejected"`: return a concise message explaining the request could not be processed.
- For `status == "failed"`: return a generic retry message without exposing exception types, IDs, or technical details.
- Keep the response module free of LLM calls, SQLAlchemy queries, repository access, `db.commit`/`db.rollback`, `Session` mutation, Pedido mutation, intent mutation, HTTP / Twilio, and response beautification.
- Add focused tests in `backend/tests/api_smoke.py` covering each status branch; reuse the existing `supernova_test` database and existing services.

## Capabilities

### New Capabilities

- `agregar-producto-customer-response`: Defines the deterministic, template-based customer-facing reply for `agregar_producto`. Covers the `CustomerResponse` schema, the response builder signature and behavior across `pending_resolution` (clarification), `executed` (confirmation), `rejected` (apology), and `failed` (retry) outcomes, and the boundaries that keep this layer free of LLM, SQLAlchemy, HTTP, Twilio, and mutation concerns.

### Modified Capabilities

## Impact

- New files: `backend/intents/schemas/customer_response.py`, `backend/intents/responses/agregar_producto_response.py`, `backend/intents/responses/__init__.py`.
- New tests appended to `backend/tests/api_smoke.py` covering `pending_resolution` clarification, `executed` confirmation, `rejected` apology, `failed` retry, and the no-mutation / no-commit / no-SQL guarantee.
- Reused unchanged: `backend/intents/schemas/processed_intent.py`, `backend/intents/schemas/requirement_state.py`, `backend/services/producto_query_service.py`, `backend/repositories/producto_query_repository.py`, `backend/models/session.py`, `backend/models/producto_presentacion.py` (read-only).
- Not touched: `backend/intents/handlers/agregar_producto_handler.py`, `backend/intents/orchestration/transactional_message_processor.py`, `backend/intents/orchestration/incoming_message_orchestrator.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/services/pedido_producto_service.py`, `backend/llm/*`, `backend/routers/*`, `backend/dependencies/*`, recognizers, resolvers, processors, contracts, models, migrations.
- Not introduced: LLM calls, SQLAlchemy direct queries, repository imports, `db.commit`/`db.rollback`, `Session`/`Pedido`/`intent` mutation, HTTP / Twilio integration, response beautification, response objects for other intents, retry/backoff/async wrappers.