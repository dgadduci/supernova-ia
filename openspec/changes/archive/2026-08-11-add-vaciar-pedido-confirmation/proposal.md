# Add explicit confirmation before clearing a draft order

## Objective

Allow a customer to request `vaciar_pedido` and, only after an explicit affirmative reply, delete every line from that customer's active draft order.

## Current execution path

Local and provider inbound messages both reach `process_incoming_message_transactional`, then `process_incoming_message`. With no `session.context_type`, `dispatch_initial_message` invokes the authoritative classifier. `VACIAR_PEDIDO` already exists in that classifier contract and prompt, but has no dispatcher branch, context, handler, response builder, or mutation service. A non-null context instead routes the raw next message directly to `dispatch_pending_context`, ahead of classification. The outer transactional processor owns commit/rollback; the shared mapper feeds both the local response and provider outbox paths.

## Scope and non-goals

- Add a deterministic, explicit `vaciar_pedido` confirmation context and the all-lines deletion it authorizes.
- Operate only on the active session's associated `borrador` pedido and only its `PedidoProducto` rows.
- Reuse the initial dispatcher, pending-context priority, transactional processor, shared response mapper, and outbox path.
- Add focused unit/integration tests for acceptance, rejection, invalid replies, stale state, isolation, and mapper/outbox equivalence.
- Do not add a migration, endpoint, LLM call, new transaction owner, parallel pipeline, catalog recognition, payment/delivery changes, order-state transition, or unrelated cleanup.

## Shared boundary, fallback, and transactions

The initial classifier is authoritative only for recognizing the initial `vaciar_pedido` request. The confirmation context is authoritative for the next turn and uses a deliberately small deterministic Spanish affirmative/negative matcher; it must not invoke the classifier or an LLM. A clear affirmative makes the intent ready; a clear negative produces a definitive cancellation; an unrecognized/ambiguous confirmation remains pending and re-prompts. It must never fall through into a fresh initial intent while the confirmation context is active.

The handler re-loads the session-associated pedido and verifies it remains the same `borrador` with at least one line before staging deletion. Missing, foreign, non-borrador, already-empty, stale, or cancelled-confirmation outcomes are valid rejected business outcomes and delete nothing. Technical database failures return/propagate as failures to the existing outer transaction owner; they are not converted into confirmation fallback.

Neither the initial orchestrator, confirmation resolver, handler, response builder, mapper, repository helper, nor service may commit, rollback, begin, close, refresh, or otherwise take transaction ownership. The existing transactional processor/coordinator remains the sole owner. The delete operation must validate before mutation and stage all line deletion atomically in that owner transaction.

## Observability, expected files, and validation

Reuse existing structured intent/status and pending-state diagnostics. Do not add raw-message or customer-response logging. Expected implementation surfaces: initial dispatcher; a narrow `vaciar_pedido` orchestrator/handler and deterministic confirmation resolver; context enum/resolver and pending dispatcher/execution registration; atomic pedido-producto service/repository operation; response builder and shared mapper; focused tests.

The user will run locally:

`venv/bin/python -m pytest backend/tests/test_vaciar_pedido.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_pending_context_execution.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/pending_context_dispatcher.py backend/intents/orchestration/pending_context_execution.py backend/intents/context/context_type_resolver.py backend/intents/handlers backend/intents/responses backend/sessions/enums/context_type.py backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py backend/tests/test_vaciar_pedido.py`

`venv/bin/python -m compileall -q backend/intents/orchestration backend/intents/context backend/intents/handlers backend/intents/responses backend/sessions/enums backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py`

`openspec validate add-vaciar-pedido-confirmation --strict`

## Reversibility and deferred limitations

The feature can be reverted in code without data migration. Restoring deleted lines is deliberately not provided; explicit confirmation is the safety boundary. Confirmation-expiry policy, undo, partial/all-line selection, voice/NLU confirmation parsing beyond the approved deterministic phrases, and clearing submitted orders remain deferred.
