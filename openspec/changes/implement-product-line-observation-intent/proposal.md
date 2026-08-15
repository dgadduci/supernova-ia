# Proposal: confirmation-time order observation

## Objective

Replace the deployed product-line-observation capability with one optional,
free-text observation for the whole Pedido during an explicit confirmation
flow. The customer supplies the note only after the system asks for it; that
reply is stored as general order text and confirms the active draft in the
same caller-owned transaction.

## Why

Product-line observations require identifying a product, presentation and
free-form condition in natural language. That is an unnecessary and fragile
language-recognition problem for the current phase. The desired operational
need is simpler: after a customer is ready to confirm, receive any instruction
for the whole order without interpreting it.

## Current execution path

`confirmar_pedido` currently validates the active session's own `borrador`,
its lines, payment and delivery, then directly transitions the Pedido to
`ingresado`. `set_observacion_pedido` already normalizes 1–500 characters and
replaces `Pedido.observaciones`, but it is a classifier-dispatched route.

The deployed `set_observacion_producto` path instead uses classifier prompt
guidance, a current-order line recognizer, `order_line_selection` pending
state, a dedicated `PedidoProducto.observaciones` write seam and a response
mapper branch. That path is the capability being withdrawn. Existing line
values are historical data; they are not a target for deletion or migration.

## Scope

- A valid explicit `confirmar_pedido` request shall first open a dedicated
  `order_confirmation_observation` pending context and ask:
  `¿Querés agregar alguna observación al pedido? Escribila ahora o respondé
  “no”.`
- Exact normalized `no` shall skip the write and confirm the order. Any other
  non-empty, in-range text shall become `Pedido.observaciones` and confirm
  automatically in the same outer transaction.
- The capture turn bypasses initial classification and treats its input as
  opaque text. It does not use an LLM, product recognizer, catalog, line
  selection or grammar.
- The final turn shall revalidate active session, ownership, `borrador`,
  non-empty lines, payment and delivery before staging the observation and
  state transition.
- Direct product-line and direct general-observation intents outside this
  context shall be rejected with deterministic guidance, not executed.
- The product-line observation modules, dispatch/mapper/pending branches,
  dedicated line-write seam, focused tests and line-observation panel field
  shall be removed where no longer used.
- A persisted pre-deploy product-line observation pending state shall be
  cleared safely on its next turn, without running its handler or writing a
  line.

## Non-goals

- No automatic inference that a customer has finished selecting products; the
  prompt occurs only after explicit confirmation.
- No observations while adding, removing or modifying products, and no
  combined add-with-observation behavior.
- No append/merge behavior: a submitted observation replaces the previous
  `Pedido.observaciones` value, consistent with the existing order-level
  contract.
- No database migration, purge or copy of existing `PedidoProducto`
  observation data; no schema/enum cleanup, router/CLI/outbox redesign or
  temporal-delivery work.

## Authoritative outcomes and fallback

`pending_resolution` means the validated confirmation request is waiting for
either `no` or free text. `executed` means exact `no` confirmed the order, or
valid text was stored on the Pedido and then the order was confirmed. Empty or
over-limit text is a non-mutating retry that preserves the pending context.
Missing/invalid ownership, state or confirmation prerequisites are rejected
without mutation. Technical failures propagate to the existing transaction
owner and never turn into success.

There is no language fallback: non-`no` capture text is neither classified nor
parsed. Outside the context, an observation-like message cannot fall back to a
line, catalog, recent product, generic recognition or LLM guess.

## Transaction ownership and observability

The confirmation orchestrator, capture resolver, finalizer, response builder
and mapper shall not call `commit`, `rollback`, `flush`, `refresh`, `begin` or
`close`. The established incoming-message transaction commits both staged
Pedido changes once or rolls them back together.

No new diagnostic field or customer response may include the observation text,
customer content, IDs, pending JSON or raw classifier/LLM output. The panel
may show the order-level note as order data, but not historical line notes as
an active feature.

## Expected files

- `backend/intents/orchestration/draft_order_closure.py`
- `backend/intents/context/order_confirmation_observation_resolver.py` (new)
- `backend/sessions/enums/context_type.py`
- `backend/intents/context/context_type_resolver.py`
- `backend/intents/orchestration/pending_context_dispatcher.py`
- `backend/intents/orchestration/pending_context_execution.py`
- `backend/intents/orchestration/initial_intent_dispatcher.py`
- `backend/intents/responses/draft_order_closure.py`
- `backend/services/outbound_response_mapper.py`
- `backend/diagnostics/prompt_template.py` and `backend/diagnostics/intent_corpus.py`
- only the product-line observation modules, service/repository seam, panel
  view/template and tests that become unreachable by this change.

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this project's
Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_observation.py backend/tests/test_draft_order_closure.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_pending_context_execution.py backend/tests/test_outbound_response_mapper.py backend/tests/test_intent_classifier.py backend/tests/test_prompt_template_grounding.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/draft_order_closure.py backend/intents/context/order_confirmation_observation_resolver.py backend/intents/orchestration/pending_context_dispatcher.py backend/intents/orchestration/pending_context_execution.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/draft_order_closure.py backend/intents/context/order_confirmation_observation_resolver.py backend/intents/orchestration/pending_context_dispatcher.py backend/intents/orchestration/pending_context_execution.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py
openspec validate implement-product-line-observation-intent --strict
git diff --check
```

## Reversibility and deferred limitations

The change is reversible by restoring the removed line-observation code and
branches through a deployment rollback. It does not change schema or erase
historical data. Editing an observation after confirmation, accumulating
multiple notes, and combined product-add conditions remain deferred.

## Hold and archive gate

The formerly planned product-line production gates are superseded and are not
archive gates. This change remains active until focused validation passes and
the user verifies two deployed confirmation turns: one `no` and one free-text
note. Archive requires separate explicit user approval.
