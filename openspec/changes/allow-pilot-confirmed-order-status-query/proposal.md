# Proposal: allow flexible status queries for the confirmed pilot order

## Why

The pilot panel's local-test route currently rejects every selected order that
is no longer `borrador`. This correctly prevents post-confirmation product or
session mutations, but it also prevents a customer from asking for the status
of that same confirmed order. In practice, an operator sees only the generic
local-channel rejection before the message reaches intent classification.

The customer must be able to phrase a status question naturally. A fixed list
of Spanish phrases is not an adequate customer contract. The LLM may classify
that language, but it must never be the authority that permits a mutation on a
confirmed order.

## What Changes

Add one narrow branch to `POST /admin/pilot/orders/{pedido_id}/local-test` for
the exact selected, active-session, confirmed order:

1. Retain the current draft (`borrador`) route and its existing full message
   pipeline unchanged.
2. For the exact selected order in a confirmed-or-later state, call the
   existing intent classifier only to interpret the submitted text.
3. Execute a status response only when the classifier returns exactly one
   `consultar_estado_pedido` intent. Reuse the existing read-only
   `process_initial_order_status_query` and shared response mapper.
4. Reject every other classifier result, multi-intent result, classifier
   schema/transport failure, pending context, or identity/ownership mismatch
   with the existing generic local-test rejection. No fallback to the normal
   transactional message pipeline is permitted.

The route remains local-panel-only: it does not alter WhatsApp/Twilio,
provider processing, the global dispatcher, classifier prompt/corpus, order
confirmation, or status-query behavior outside this endpoint.

## Current execution path

`local_test_message` currently calls `_load_local_test_session`, which accepts
only the exact active session whose associated order is `borrador`; it then
calls `process_incoming_message_with_responses`. This is why an `ingresado`
order is rejected before classification. The existing status orchestration
already reads only `session.id_pedido`, verifies session ownership, and returns
the persisted status without mutation. Conversely, the normal dispatcher can
execute `iniciar_pedido`, product, or order mutations, so it must not be used
for confirmed orders.

## Scope

- Exact selected pilot order only, with the session already associated to that
  order and active.
- Natural-language status classification through the existing `IntentClassifier`.
- One allowlisted, read-only execution outcome:
  `consultar_estado_pedido`.
- Existing generic rejection body, response mapper, safe post-turn snapshot,
  panel authentication, same-origin header, and bounded request body.

## Non-goals

- No post-confirmation add/remove/modify/clear/confirm/cancel/new-order flow.
- No change to WhatsApp/Twilio/provider/outbox/worker processing.
- No prompt, corpus, enum, model, database, migration, router family, or
  panel-template change.
- No deterministic vocabulary expansion for status queries.
- No fallback session/order lookup, successor session creation, or changes to
  already active pending-context semantics.

## Shared boundary and authoritative outcomes

The existing LLM classifier is a language parser, not a mutation authority.
For the confirmed local order, the route accepts only one classified intent
and only when it is `consultar_estado_pedido`:

| Condition | Outcome |
| --- | --- |
| Exact active, consistent draft | Existing full local-test pipeline; unchanged |
| Exact active, consistent non-draft; classifier yields exactly one status intent; no pending context | Existing read-only status orchestration and shared response mapper |
| Any other intent or more than one intent | Generic local rejection; no pipeline call |
| Empty/invalid classifier payload or classifier technical failure | Generic local rejection; no pipeline call |
| Pending context, missing/foreign/repointed session/order, inactive session, client/comercio inconsistency | Generic local rejection; no classifier execution or fallback target |

The pending-context condition is deliberately fail-closed: no status query may
bypass a still-active context for a confirmed order.

## Transactions, privacy, observability, rollback

The confirmed-order status path is read-only. The router, classifier gate,
status orchestration, and mapper do not call transaction-control methods or
write pending state, session state, order state, order lines, provider rows, or
outbox rows. Technical classifier failures are deliberately not exposed in the
HTTP body or transcript. Existing safe diagnostics may record only bounded
classification metadata; they must not add customer text, IDs, pending JSON,
or exception detail to a newly exposed panel/API surface.

The change is reversible by removing the confirmed-order branch; drafts retain
their existing behavior throughout. No data migration or durable state change
is required.

## Expected files

- `backend/routers/admin_pilot_orders.py`
- `backend/tests/test_admin_pilot_orders_panel.py`
- optionally an existing focused status-query/router test module only when
  necessary to cover the shared read-only boundary
- `openspec/changes/allow-pilot-confirmed-order-status-query/**`

## Focused validation

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_order_status_query.py backend/tests/test_initial_intent_dispatcher.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/routers/admin_pilot_orders.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_order_status_query.py backend/tests/test_initial_intent_dispatcher.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers/admin_pilot_orders.py
openspec validate allow-pilot-confirmed-order-status-query --strict
git diff --check
```

## Deferred limitations

This does not enable general conversation or later order modifications after
confirmation. Any future provider-channel status-query policy needs its own
OpenSpec and safety review.
