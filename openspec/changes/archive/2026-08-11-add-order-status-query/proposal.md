# Add WhatsApp order-status query

## Objective

Allow a customer to ask for the status of the pedido already associated with
their active WhatsApp conversation, using the existing
`consultar_estado_pedido` classifier intent. The result is read-only and gives
only a safe, customer-facing state description.

## Current execution path

The provider webhook persists a receipt and deferred work item. Its existing
coordinator resolves the authoritative channel, commerce, client and active
conversation session, preserves an existing `session.id_pedido` association,
then calls `process_incoming_message`. With no `context_type`,
`dispatch_initial_message` calls the authoritative classifier. The enum and
prompt already include `consultar_estado_pedido`, but the dispatcher has no
branch for it, so it becomes a rejected generic response. Processed intents
are rendered by the shared outbound response mapper and staged into the durable
outbox; local processing uses the same mapper. The existing outer transactional
processor/coordinator owns commit and rollback.

`Pedido` already has the authoritative states `borrador`, `ingresado`,
`preparacion`, `terminado`, `entregado`, and `cancelado`. Its established
transition policy is unchanged. The archived guided-closure change confirms
`borrador -> ingresado`; the archived new-order change may later replace that
session only when `iniciar_pedido` is requested.

## Scope and non-goals

- Dispatch the existing `consultar_estado_pedido` intent to one narrow,
  read-only status-query orchestrator.
- Resolve exactly `session.id_pedido` and require the loaded pedido to belong
  to that same session.
- Render deterministic Spanish status messages through the existing shared
  mapper for local and durable-outbox paths.
- Cover no association, stale/foreign association, all supported states,
  pending-context priority, response safety/equivalence, and transaction
  neutrality with focused tests.
- Do not add a migration, endpoint, new queue/pipeline, LLM/prompt change,
  LangGraph, recognizer, repository search, history lookup, state transition,
  retry policy, retention/purge work, or unrelated cleanup.

## Shared boundary, fallback, and transactions

The existing classifier remains authoritative only for naming the initial
intent. A non-null pending context retains its established priority, so a
status-looking message in that context is handled by that context and never
falls through to a new query or widens pending candidates.

The query loads no order other than `session.id_pedido`; it validates
`Pedido.id_session == session.id`. Missing, stale, or foreign associations are
valid `rejected` business outcomes with no fallback search by customer,
commerce, channel, or historic order. A valid associated pedido in any of the
six existing states is `executed`: `borrador` is reported as still being
assembled; `ingresado`, `preparacion`, and `terminado` as the corresponding
post-confirmation progress; and `entregado`/`cancelado` as terminal outcomes.
No state changes, pending-intent changes, or session reassociation occur.

Technical database/programming failures propagate to the existing transaction
owner and follow its rollback/retry policy. They are not converted to a
business fallback and must not generate a success answer. The orchestrator,
response builder, dispatcher branch, and mapper integration do not call
`commit`, `rollback`, `begin`, `flush`, `refresh`, `expire`, or `close`.

## Observability, expected files, and validation

Reuse existing structured processed-intent, pending-state, provider-processing,
and outbound-attempt observability. Do not log raw message bodies, rendered
customer text, database IDs, payment/delivery selections, line items, address,
or other customer/order detail.

Expected implementation surfaces are limited to the initial dispatcher; a
read-only status-query orchestration module; its deterministic response
builder; the shared outbound response mapper; and one focused test module
(plus an existing focused dispatcher/mapper test only if it is the established
home). No model, migration, settings, provider coordinator, outbox schema, or
repository/service expansion is expected.

The implementer must run locally and report complete output:

`venv/bin/python -m pytest backend/tests/test_order_status_query.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_outbound_response_mapper.py backend/tests/test_incoming_message_response_orchestrator.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/order_status_query.py backend/intents/responses/order_status_query.py backend/services/outbound_response_mapper.py backend/tests/test_order_status_query.py`

`venv/bin/python -m compileall -q backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/order_status_query.py backend/intents/responses/order_status_query.py backend/services/outbound_response_mapper.py`

`openspec validate add-order-status-query --strict`

## Reversibility and deferred limitations

The change is reversible by removing its dispatcher and mapper branches; it
has no schema or data migration. Order-history lookup, selecting among multiple
orders, ETA, courier/location tracking, item/price/payment/delivery disclosure,
merchant workflows, cancellation, and durable-message retention/purge remain
deferred.
