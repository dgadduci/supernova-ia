# Proposal: implement product-line observation intent

## Objective

Make the existing `set_observacion_producto` classification executable in the
modern incoming-message path. It will set or explicitly clear the
`PedidoProducto.observaciones` value of exactly one line belonging to the
active conversation's own draft Pedido, and will return a deterministic
customer response.

## Current execution path

`IntentName` and the classifier prompt/corpus already contain
`set_observacion_producto`. `dispatch_initial_message` has no branch for it,
so it reaches the generic rejected fallback. No handler, response builder, or
pending-context rule exists for this intent.

The analogous `quitar_producto` path recognizes only lines loaded from
`session.id_pedido`, persists ambiguous line ids in `order_line_selection`,
and uses `resolve_order_line_selection` to intersect a clarification with the
stored set. `PedidoProducto.observaciones` is nullable, but the legacy
`PedidoProductoService.update` owns commits/rollbacks and treats `None` as
“unchanged”; it cannot safely implement an in-turn clear operation.

The outer `process_incoming_message_transactional` and provider coordinator
own commit/rollback. `build_customer_responses` maps known processed intents
to deterministic builders after processing.

## Scope

- Add a narrow recognizer/orchestrator/handler/response flow for
  `set_observacion_producto`.
- Identify candidates exclusively from current `PedidoProducto` lines of
  `session.id_pedido`; the final identifier is `pedido_producto_id`.
- Reuse `order_line_selection` and its intersection-only refinement for an
  ambiguous reference; the initial observation action/text survives the
  clarification in `resolved_data`.
- Add a dedicated PedidoProducto service/repository write seam that validates
  active-session ownership and draft state, accepts a nullable observation,
  and leaves commit/rollback/flush ownership to the caller.
- Map pending, executed, rejected and failed outcomes to fixed Spanish
  responses without exposing ids or the stored observation content.

## Non-goals

- No change to the classifier enum, prompt, corpus, LLM schema, catalog,
  product-recognition policy, HTTP endpoint, CLI, outbox contract, migration,
  pedido-level observation intent, or temporal-delivery programming spec.
- No catalog lookup, candidate widening, new pending context type, queue
  semantics, confirmation turn, LLM extraction/paraphrasing, or LLM-selected
  mutation target.
- No repair of the legacy `add`, `update`, or `delete` service transaction
  behavior outside the new seam.

## Shared boundary and authoritative outcomes

The classifier only selects the existing intent branch; it is not authority
for line selection, clear/set action, stored value normalization, or mutation.
The user-supplied `classified.mensaje` is preserved as the raw observation
text for a set action after local trimming. A local deterministic clear grammar
alone may produce `None`: a normalized message must contain an explicit
observation/aclaración noun and a clear verb (`quitar`, `sacar`, `eliminar`,
or `borrar`, including supported inflections), or the exact phrase `sin
observación` / `sin aclaración`. All other non-empty inputs are set actions.

Authoritative outcomes are:

- `executed`: one validated line of the active session's own `borrador` is
  updated to the trimmed raw text, or `NULL` for an explicit clear.
- `pending_resolution`: more than one candidate line matched; the action and
  raw text are persisted with only those `pedido_producto_id` candidates.
- `rejected`: no active/own draft, inactive session, absent/foreign line,
  non-borrador Pedido, no candidate, or a clarification outside the stored
  candidate set. No row changes.
- `failed`: an unexpected technical failure; it reaches the existing outer
  transactional owner, which rolls back the turn.

Fallback is deliberately safe: fuzzy recognition remains the existing
order-line recognizer and its result is accepted only after intersection with
the pending set and service-side ownership/state validation. A no-match or
ambiguous result never falls back to the commerce catalog, a different order,
the most recent line, or an LLM guess. A technical failure never becomes a
success response.

## Transaction ownership and observability

Recognizer, orchestrator, resolver, handler, response builder, repository,
and new service seam SHALL not commit, rollback, begin, close, or flush. The
handler validates active session state; the new service validates
`Pedido.id_session == session.id`, line membership in `session.id_pedido`, and
`borrador` before assigning the nullable column. Existing processing
transaction owners commit once on success and roll back the full turn on
exceptions.

The existing diagnostic sink may retain intent/status/candidate-count metadata
through current dispatcher/resolver seams. It SHALL NOT emit observation text,
customer content, product-line ids, or any raw LLM output as a new diagnostic
field. Customer responses identify only the product display label, never the
stored observation.

## Expected files

- `backend/intents/recognizers/set_observacion_producto_recognizer.py`
- `backend/intents/orchestration/set_observacion_producto_initial.py`
- `backend/intents/handlers/set_observacion_producto_handler.py`
- `backend/intents/responses/set_observacion_producto_response.py`
- Narrow branches in initial dispatch, context-type resolution, ready pending
  execution, and outbound response mapping; reuse the existing order-line
  resolver/dispatcher.
- `backend/services/pedido_producto_service.py` and
  `backend/repositories/pedido_producto_repository.py` for the dedicated
  caller-owned mutation seam.
- Focused tests beside the existing quitar/modificar, pending-context, mapper,
  and transaction-regression tests.

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this project's
Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_set_observacion_producto_initial.py backend/tests/test_set_observacion_producto_handler.py backend/tests/test_set_observacion_producto_response.py backend/tests/test_set_observacion_producto_end_to_end.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_pending_context_execution.py backend/tests/test_outbound_response_mapper.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/set_observacion_producto_recognizer.py backend/intents/orchestration/set_observacion_producto_initial.py backend/intents/handlers/set_observacion_producto_handler.py backend/intents/responses/set_observacion_producto_response.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/context/context_type_resolver.py backend/intents/orchestration/pending_context_execution.py backend/services/outbound_response_mapper.py backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/set_observacion_producto_recognizer.py backend/intents/orchestration/set_observacion_producto_initial.py backend/intents/handlers/set_observacion_producto_handler.py backend/intents/responses/set_observacion_producto_response.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/context/context_type_resolver.py backend/intents/orchestration/pending_context_execution.py backend/services/outbound_response_mapper.py backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py
openspec validate implement-product-line-observation-intent --strict
```

## Rollback and deferred limitations

This is source-only and reversible: removing its dispatcher/mapper branches
returns the intent to its current rejected behavior; data already stored in
the nullable `observaciones` field requires no rollback migration. The initial
grammar intentionally favors safety over broad natural-language parsing;
unsupported deletion phrasings become a set action or a business rejection
rather than deleting data. Rich structured observation extraction, editing
pedido-level observations, and a broader natural-language clear grammar are
deferred to separately approved work.

## Hold and archive gate

## Operational pause

This change remains paused. Its production-message test must not begin until
the corrective change has resumed and passed its own production gate after
the separately proposed `add-pilot-order-operations-panel` is approved,
implemented and deployed. This is a pause only: it neither archives this
change nor authorizes any implementation or manual data operation.

This change is intentionally **not ready to archive**. The separate active
change `fix-pending-context-recovery-and-status-query` MUST first be
implemented, locally validated, reviewed, deployed through the normal
approved path, and verified in production with real WhatsApp messages. Only
after that production verification demonstrates both a successful product
selection and recovery/status behavior may this observation change be resumed
for its own production-message test. Archive is permitted only after that
resumed test succeeds and the user explicitly approves archiving; neither
change may be archived merely because its code or focused tests pass.
