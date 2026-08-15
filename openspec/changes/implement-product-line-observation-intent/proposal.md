# Proposal: implement product-line observation intent

## Objective

Make the existing `set_observacion_producto` classification executable in the
modern incoming-message path. It will set or explicitly clear the
`PedidoProducto.observaciones` value of exactly one line belonging to the
active conversation's own draft Pedido, and will return a deterministic
customer response.

## Regression amendment: declarative product instructions

Pilot traffic showed that `La pizza de mozzarella chica es sin aceitunas`
reached the `agregar_producto` fallback and returned `No pude procesar tu
pedido, ¿podrías reformularlo?`. The product-line-observation mapper does not
emit that response, so the failure occurs in classification before the
existing order-line recognizer runs.

The bounded correction is static classifier calibration: a declarative,
product-specific instruction with no add verb must produce exactly one
`set_observacion_producto` intent and preserve the original message. It must
not inspect the current Pedido to reinterpret an add request. In particular,
`quiero una pizza de mozzarella chica sin aceitunas` remains an add request;
combined add-with-observation is deferred to a separately approved change.

The deployed classifier amendment now reaches the observation path, but the
pilot proved a second, independent boundary failure: an active draft containing
`Mozzarella / Chica` rejected `La pizza de mozzarella chica es sin aceitunas`
as absent. The observation recognizer delegates the entire free-text message
to the current order-line fuzzy recognizer; the condition suffix prevents it
from recovering the otherwise-present line. This is not a classifier, service,
or ownership failure.

## Current execution path

`IntentName`, the classifier prompt/corpus, initial dispatcher, order-line
recognizer, orchestrator, handler, response mapper and caller-owned
`PedidoProducto.observaciones` seam already exist and are deployed. The
remaining production failure is that the static classifier guidance has only
the generic `La pizza es sin aceitunas` example and did not reliably classify
the observed qualified declarative phrasing.

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
- Calibrate only the static classifier prompt and controlled corpus for the
  observed declarative wording, then prove the existing dispatcher receives
  the classified intent unchanged.
- When the existing bounded order-line fuzzy recognizer returns no candidate
  for an already-classified observation, recover candidates only from
  deterministic identity evidence already present in the complete raw message
  and in the active draft's own line catalog. This is not grammatical clause
  extraction and does not enumerate observation verbs.

## Non-goals

- No change to the classifier enum, LLM schema, catalog,
  product-recognition policy, HTTP endpoint, CLI, outbox contract, migration,
  pedido-level observation intent, or temporal-delivery programming spec.
- No catalog lookup, candidate widening, new pending context type, queue
  semantics, confirmation turn, LLM extraction/paraphrasing, or LLM-selected
  mutation target.
- No repair of the legacy `add`, `update`, or `delete` service transaction
  behavior outside the new seam.
- No state-aware classifier rule, current-Pedido lookup, post-classification
  rewrite, or fallback from `agregar_producto` to
  `set_observacion_producto`. Combined add-with-observation remains out of
  scope.
- No deterministic parsing of declarative verbs or separators such as `es`,
  `va`, `lleva`, `con`, or `sin`; no broad support for imperative wording
  such as `poné`, `agregale`, or `sacale`; no LLM extraction of a product
  reference; and no most-recent-line heuristic. Those broader language
  decisions remain deferred.

## Shared boundary and authoritative outcomes

The classifier selects the existing intent branch from message wording only;
it never reads the current Pedido and is not authority
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

For this amendment, `La pizza de mozzarella chica es sin aceitunas` SHALL
classify as one `set_observacion_producto` intent. `quiero una pizza de
mozzarella chica sin aceitunas` SHALL remain `agregar_producto`; an existing
matching line must not silently change that action.

For the same classified declarative observation, candidate recovery SHALL use
the full raw message unchanged. It may consider only normalized identity tokens
already projected by the current draft's own line catalog (product,
presentation, category and existing aliases). It SHALL never split the message
on an observation verb or condition. Exactly one bounded candidate may become
ready; multiple candidates remain pending and zero candidates remain rejected.
The raw full message remains the value persisted for a set action.

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
- `backend/diagnostics/prompt_template.py`,
  `backend/diagnostics/intent_corpus.py`, and focused classifier/dispatcher
  tests for the regression amendment.
- `backend/intents/recognizers/set_observacion_producto_recognizer.py` and
  focused observation-recognizer/end-to-end tests for the bounded identity
  recovery amendment.
- Focused tests beside the existing quitar/modificar, pending-context, mapper,
  and transaction-regression tests.

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this project's
Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_set_observacion_producto_initial.py backend/tests/test_set_observacion_producto_handler.py backend/tests/test_set_observacion_producto_response.py backend/tests/test_set_observacion_producto_end_to_end.py backend/tests/test_set_observacion_producto_recognizer.py backend/tests/test_quitar_producto_recognizer.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_intent_classifier.py backend/tests/test_prompt_template_grounding.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_pending_context_execution.py backend/tests/test_outbound_response_mapper.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/set_observacion_producto_recognizer.py backend/tests/test_set_observacion_producto_recognizer.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_classifier.py backend/tests/test_prompt_template_grounding.py backend/tests/test_initial_intent_dispatcher.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/set_observacion_producto_recognizer.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/llm/intent_classifier.py backend/intents/orchestration/initial_intent_dispatcher.py
openspec validate implement-product-line-observation-intent --strict
```

## Rollback and deferred limitations

The amendments are reversible by reverting the static prompt/corpus revision
and the candidate-recovery fallback; neither changes existing persisted rows
outside a successful observation turn. Combined add-with-observation, rich
structured extraction, pedido-level observations, imperative observation
language, and broader clear grammar remain deferred to separately approved
work.

## Hold and archive gate

## Operational pause

The prerequisite product-add and pending-context gates have passed in the
pilot. This amendment authorizes only bounded prompt/corpus calibration after
user approval; it neither archives this change nor authorizes combined
add-with-observation behavior.

This change is intentionally **not ready to archive**. It needs review of the
deployed implementation, this classifier amendment, focused validation and a
controlled production set/clear test before explicit user archive approval.
