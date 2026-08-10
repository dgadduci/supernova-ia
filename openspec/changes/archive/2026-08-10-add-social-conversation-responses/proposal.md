# Add deterministic social conversation responses

## Objective

Make the existing WhatsApp conversation respond briefly and contextually to the classifier's already-defined social intents: `saludo`, `agradecimiento`, `despedida`, `respuesta_afirmativa`, `respuesta_negativa`, and `desconocida`.

## Current execution path

Provider and local traffic both reach `process_incoming_message`, which routes an initial turn to `dispatch_initial_message`. The classifier and its prompt already emit the six social intent names, but the dispatcher falls through to a rejected `ProcessedIntent`; `build_customer_responses` then maps every unrecognized intent to the same generic rejection message before the existing outbox/local-response path.

## Scope and non-goals

- Route the six existing social intents through a small deterministic, non-mutating orchestration path.
- Add fixed, brief Spanish customer responses through the existing response mapper and outbox path.
- Make `desconocida` a contextual recovery response instead of treating it like a technical rejection.
- Preserve classifier names, schema, prompt policy, pending-context dispatch, order mutations, response ordering, and the existing generic fallback for unsupported future intents.
- Do not add LLM styling, informational/catalog queries, `vaciar_pedido`, models, migrations, endpoints, workers, queues, or another pipeline.

## Shared boundary, fallback, and transactions

The classifier remains authoritative for selecting one of these six intent names. The initial dispatcher may create only a typed `ProcessedIntent`; it must not inspect or mutate pedido/session state beyond its existing context guard. A non-null pending context continues to bypass initial dispatch entirely, so affirmative/negative text cannot escape a pending selection or closure context.

All six outcomes are valid, successful, non-mutating business outcomes. `desconocida` is the only user-facing fallback when the classifier cannot safely interpret a message. A technical classifier, database, mapper, or outbox error is not `desconocida` and must propagate to the existing transaction owner unchanged. No component in this change commits, rolls back, begins, closes, refreshes, or expires a transaction.

## Observability, expected files, and validation

Reuse `ProcessedIntent`, the initial dispatcher, `build_customer_responses`, and the staged outbox path. Existing structured intent/status diagnostics remain sufficient; do not log raw customer text or response text. Expected implementation files are the dispatcher, one small social-response builder module, the mapper, and focused unit/integration tests.

The user will run locally:

`venv/bin/python -m pytest backend/tests/test_initial_intent_dispatcher.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/social_conversation_response.py backend/services/outbound_response_mapper.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py`

`venv/bin/python -m compileall -q backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/social_conversation_response.py backend/services/outbound_response_mapper.py`

`openspec validate add-social-conversation-responses --strict`

## Reversibility and deferred limitations

The new dispatcher branches and builder mapping can be reverted without data repair because no state is written. Response personalization, LLM styling, whether an affirmative/negative should act on a future non-pending question, catalog/configuration queries, and all order-changing intents remain deferred to their respective approved OpenSpec changes.
