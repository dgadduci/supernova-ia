## Why

Subphase 3.24 shipped `process_incoming_message` with focused unit tests (`backend/tests/test_incoming_message_orchestrator.py`, 21 tests) that patch `dispatch_initial_message` and `dispatch_pending_context` with `MagicMock` returns. Those tests prove the routing rule, message validation, pending-result wrapping, order preservation, error propagation, and no-commit guarantee in isolation, but they do not exercise the real `IntentClassifier`, the real `process_initial_agregar_producto` orchestrator, the real recognizer/resolver/processor/handler/services, or the `supernova_test` database. Subphase 3.25 adds the missing integration test so that both routing branches are verified end-to-end against real application components, with only the external LLM classification boundary mocked — without touching any production code unless the test exposes an integration defect.

## What Changes

- Add `backend/tests/test_incoming_message_integration.py` exercising the full `process_incoming_message` pipeline against `supernova_test`, with minimal fixtures and no mocks on the main flow.
- Cover the **initial-message branch** (one test): seed commerce, client, active session, draft `Pedido`, and a `Producto` with two active presentations (`chica`, `grande`) plus prices; mock only `IntentClassifier` to return one `agregar_producto`; call `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")`; assert exactly one `ProcessedIntent` is returned with `status == "pending_resolution"`, `session.context_type == "product_selection"`, the active pending intent is persisted, and no `PedidoProducto` row exists.
- Cover the **pending-context branch** (one test): continue from a session that already has an active `product_selection` pending context; call `process_incoming_message(db, session, "la grande")`; assert `IntentClassifier` is not called, one `ProcessedIntent` is returned with `status == "executed"`, exactly one `PedidoProducto` is created with presentation `grande` and `cantidad == 2`, `session.pending_intents` is empty, and `session.context_type is None`.
- Use real orchestrators, recognizer, resolver, dispatcher, handler, and services; mock only the external LLM classification boundary (`IntentClassifier.query`).
- Do not implement transaction management, response generation, HTTP, FastAPI, or Twilio layers.
- Do not modify production code unless the integration test exposes a defect; do not duplicate scenarios already covered by Subphase 3.19's `agregar-producto-end-to-end` suite; do not re-test unsupported intents, invalid messages, or internal-unit-level behavior.
- Extend the existing `incoming-message-orchestrator` spec with two integration scenarios that document the new integration coverage.

## Capabilities

### New Capabilities

None. This change only adds tests; it introduces no new production module or orchestrator.

### Modified Capabilities

- `incoming-message-orchestrator`: Adds two integration-test scenarios — one for the initial-message branch (`status == "pending_resolution"`, `session.context_type == "product_selection"`, pending intent persisted, no `PedidoProducto`) and one for the pending-context branch (`status == "executed"`, `PedidoProducto` created, `session.pending_intents` empty, `session.context_type is None`). Both scenarios SHALL be exercised against `supernova_test` with real components and only `IntentClassifier.query` mocked. No requirement-level behavior of the orchestrator itself changes; the addition is purely a documentation of the integration-test contract that now exists.

## Impact

- New file: `backend/tests/test_incoming_message_integration.py` (integration tests using `supernova_test`).
- Modified file: `openspec/specs/incoming-message-orchestrator/spec.md` (two new integration scenarios appended).
- Reused unchanged: `backend/intents/orchestration/incoming_message_orchestrator.py`, `backend/intents/orchestration/initial_intent_dispatcher.py`, `backend/intents/orchestration/pending_context_dispatcher.py`, `backend/intents/orchestration/agregar_producto_orchestrator.py`, `backend/llm/intent_classifier.py`, `backend/llm/query_llm.py`, recognizers, resolvers, processors, handlers, services, repositories, models, migrations, configuration, FastAPI dependencies.
- Mocked only: `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier` (the external LLM classification boundary), replaced with a stub that returns a pre-built `IntentClassificationResult` containing one `agregar_producto` classified intent. The pending-context branch asserts `IntentClassifier` is never constructed.
- Not touched: routers, Twilio integration, queue promotion, logging, retry/backoff, async wrappers, response shaping.
- `backend/old_project/` remains reference-only; nothing is imported from it.
- No new production code is introduced. If the test exposes a defect, the change author must roll the fix into a separate subphase rather than fold it into this change.