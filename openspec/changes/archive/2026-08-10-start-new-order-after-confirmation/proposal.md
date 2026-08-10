# Start a new order after confirmation

## Objective

Allow a customer to explicitly start another order after the session-associated order has left `borrador`. The prior order and session history remain intact; the same commerce/customer pair receives one fresh active session and one empty `borrador` pedido.

## Current execution path

Provider traffic follows receipt → deferred work lease → active-session/draft staging → `process_incoming_message` → response/outbox → final commit. Local traffic reaches the same orchestration through `process_incoming_message_transactional`. The classifier and prompt already define `iniciar_pedido`, but `initial_intent_dispatcher` has no branch for it and returns a rejected intent. The provider coordinator stages a draft only when an active session has no associated pedido; it never replaces an existing association.

## Scope and non-goals

- Dispatch `iniciar_pedido` to a narrow new-order transition.
- If the associated pedido is `ingresado`, `preparacion`, `terminado`, `entregado`, or `cancelado`, close the active session and stage a fresh active session plus empty `borrador` pedido for the same commerce/client.
- If the associated pedido is `borrador`, keep the active session and pedido unchanged and guide the customer to continue it.
- Add the corresponding deterministic customer response and focused tests.
- Do not alter classifier names or prompt policy; ambiguous messages remain governed by the existing classifier.
- Do not copy lines, payment, delivery, observations, pending state, or any other field from the prior pedido/session.
- No migration, endpoint, worker, queue, catalog, recognition, order-status, fulfillment, or cancellation work.

## Shared boundary, fallback, and transactions

The transition is called only by the existing initial dispatcher after the classifier has authoritatively produced `iniciar_pedido`. It uses only the supplied active session and its `id_pedido`; it neither searches for nor switches to another commerce, customer, session, or pedido. A pending context remains an existing initial-dispatch short-circuit, so it cannot trigger a replacement.

`borrador`, missing associated pedido, or invalid session state are valid non-mutating outcomes with deterministic guidance. A non-borrador associated pedido is the only condition that creates a successor. Technical database failures propagate unchanged to the existing outer transaction owner; they do not become fallback/success responses. The local transactional processor and the provider coordinator retain commit/rollback ownership. The transition may flush only to order the close/create/association writes required by the existing one-active-session constraint; it never commits, rolls back, begins, closes, refreshes, or expires the transaction.

## Observability, expected files, and validation

Reuse `ProcessedIntent` and the existing response/outbox path. Record only structured intent status/reason and opaque IDs already present in the processing path; do not log customer text. Expected implementation files are the initial dispatcher, a small new-order orchestration/response module, response mappers, and focused tests; no models or migrations.

The user will run locally:

`venv/bin/python -m pytest backend/tests/test_initial_intent_dispatcher.py backend/tests/test_new_order_after_confirmation.py backend/tests/test_provider_inbound_processing.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/new_order_after_confirmation.py backend/intents/responses/new_order_after_confirmation.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/services/outbound_response_mapper.py backend/tests/test_new_order_after_confirmation.py`

`venv/bin/python -m compileall -q backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/new_order_after_confirmation.py backend/intents/responses/new_order_after_confirmation.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/services/outbound_response_mapper.py`

`openspec validate start-new-order-after-confirmation --strict`

## Reversibility and deferred limitations

The dispatcher branch can be reverted without data migration; already-created historical sessions and orders remain valid. Starting a new order in the same multi-action message, manual session replacement APIs, reopening/copying an order, and behavior for non-explicit or classifier-ambiguous wording are deferred.
