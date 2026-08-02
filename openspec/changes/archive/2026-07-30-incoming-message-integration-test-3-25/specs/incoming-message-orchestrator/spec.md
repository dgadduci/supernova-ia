## ADDED Requirements

### Requirement: Incoming message orchestrator integration coverage

The integration test suite SHALL include a module `backend/tests/test_incoming_message_integration.py` that exercises `process_incoming_message` end-to-end against `supernova_test` with real orchestrators, recognizer, resolver, dispatcher, handler, and services. The suite SHALL mock only the external LLM classification boundary (`IntentClassifier.query`) and SHALL NOT mock any other internal component.

#### Scenario: Initial-message branch yields a pending product-selection context

- **WHEN** `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` is invoked against a session with `session.context_type is None`, a freshly seeded commerce, client, draft pedido, and a product with two active presentations (`chica`, `grande`) and prices — with only `IntentClassifier.query` mocked to return one `agregar_producto` classified intent
- **THEN** the function returns exactly one `ProcessedIntent` whose `status == "pending_resolution"`; `session.context_type == "product_selection"`; the active pending intent is persisted on the session; and no `PedidoProducto` row exists

#### Scenario: Pending-context branch executes the order line

- **WHEN** `process_incoming_message(db, session, "la grande")` is invoked against the same session immediately after the initial-message branch has established an active `product_selection` pending context
- **THEN** `IntentClassifier` is not constructed; the function returns exactly one `ProcessedIntent` whose `status == "executed"`; exactly one `PedidoProducto` row exists with the `grande` presentation and `cantidad == 2`; `session.pending_intents` is empty; and `session.context_type is None`