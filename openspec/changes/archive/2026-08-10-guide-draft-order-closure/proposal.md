# Guide draft-order closure

## Objective

Let a customer close the draft pedido already associated with their active conversation through the existing inbound pipeline: view a concise summary, choose an enabled delivery method and payment method, and explicitly confirm the order.

## Current execution path

Provider traffic follows receipt → deferred work → active session/draft pedido staging → `process_incoming_message` → response mapping → outbound outbox. Local traffic reaches the same message orchestration through the transactional processor. The classifier already emits `consultar_resumen_pedido`, `set_metodo_de_entrega`, `set_metodo_de_pago`, and `confirmar_pedido`, but the initial dispatcher currently rejects each of them, so the response wrapper emits its generic response. `Pedido` already owns nullable payment and delivery foreign keys and permits `borrador → ingresado`; the commerce configuration already records which catalog entries are enabled for each commerce.

## Scope and non-goals

- Add initial intent handling and customer responses for summary, payment, delivery, and explicit confirmation of the active draft pedido.
- Read only the session-associated `borrador` pedido and its persisted lines.
- Permit selection only from active payment and delivery methods configured for that same commerce.
- Confirm only a non-empty, complete draft by transitioning it to `ingresado`.
- No migration, schema change, endpoint, queue, address/scheduling capture, totals, stock, payment collection, merchant notification, fulfillment, or recognition-policy change.

## Shared boundary, fallback, and transactions

The closure handlers sit below the existing initial dispatcher and response orchestrator. They do not classify messages, deliver messages, or own commits. Missing, ambiguous, inactive, or commerce-foreign choices are valid non-mutating outcomes: they return a scoped clarification and leave the pedido unchanged. Missing draft, empty draft, missing required choice, or non-borrador confirmation likewise returns deterministic guidance. Technical exceptions propagate to the existing transactional owner; they must not become customer-success responses.

`process_incoming_message_transactional` owns local commits/rollbacks and `ProviderInboundMessageCoordinator.process_lease()` owns the deferred business-effects commit. New repositories, services, handlers, and response builders do not commit, roll back, flush, refresh, begin, or close sessions.

## Observability, files, and validation

Use existing structured processing/outbox observability; do not log raw messages. Expected changes are narrow closure orchestration/response modules, minimal dispatcher extensions, narrowly-scoped catalog queries, focused tests, and the delta specs. The user will run locally:

`venv/bin/python -m pytest backend/tests/test_draft_order_closure.py backend/tests/test_provider_inbound_processing.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/intents/`

`venv/bin/python -m compileall -q backend/intents`

`openspec validate guide-draft-order-closure --strict`

## Reversibility and deferred limitations

The behavior is reversible by disabling or reverting its dispatcher paths; no persisted-data migration is involved. Address and scheduling requirements, commercial totals, and downstream fulfillment remain deferred until their data model and business rules are separately approved.
