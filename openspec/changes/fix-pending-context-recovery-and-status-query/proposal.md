# Proposal: fix pending-context recovery and status query

## Objective

Correct the pending product-selection failure observed in WhatsApp and make
the resulting conversation recoverable. A reply such as `Grande` must select
the previously presented `Mozzarella Grande` candidate, a definitive rejected
clarification must not trap later messages, and an explicit order-status
question must be answerable without mutating or discarding a pending
selection. Add bounded structured operational traces that diagnose these
transitions without retaining PII.

## Current execution path

Provider processing stages an active session and own draft pedido, then calls
`process_incoming_message`. While `session.context_type` is set, the incoming
orchestrator sends every message to `dispatch_pending_context`; initial
classification, including `consultar_estado_pedido`, is bypassed. For
`product_selection`, the dispatcher calls `ProductSelectionContextService`,
persists its result, and executes only `ready` results. The product-selection
resolver already has deterministic presentation-alias narrowing, so `Grande`
is expected to resolve a restricted `Grande` candidate.

The customer text `No pude procesar tu pedido, ¿podrías reformularlo?` is
emitted only by the `agregar_producto` response builder. It therefore proves
an `agregar_producto` outcome reached a rejected/invalid pending form; it
does not prove that the order-status implementation or its response mapper
was invoked. The current dispatcher leaves a resolver-produced `rejected`
intent active because it calls pending execution only for `ready`; the next
message can consequently remain captured by that failed context.

## Scope

- Preserve the existing restricted-candidate resolver and cover the actual
  WhatsApp sequence with end-to-end tests: initial Mozzarella ambiguity,
  `Grande` selection, successful add, and cleared pending state.
- Make a definitive resolver rejection clear the active pending state and
  `session.context_type` atomically within the existing caller transaction.
- Add a small deterministic, read-only status-question predicate for explicit
  Spanish status questions while a supported pending context is active. It
  delegates only to the existing own-pedido status query and preserves the
  active pending state exactly.
- Align the classifier prompt/corpus with the existing fact that status can
  be queried for the current draft as well as a confirmed pedido.
- Add one closed structured operational event for pending-context transitions,
  emitted through the existing operational-event catalogue and query CLI.

## Non-goals

- No product-recognition policy, hybrid/fuzzy threshold, catalog, alias,
  candidate widening, new context type, LLM reclassification during pending
  context, response-text redesign, migration, endpoint, CLI chat behavior,
  provider schema, deploy, or archive.
- No fallback to the commerce catalog, another pedido, most-recent line, or
  an LLM-selected candidate.
- No raw log query, customer message text, E.164 address, session/pedido/
  product/candidate identifiers, prompt, model payload, catalog label,
  exception message, or correlation identifier in new event fields.

## Authoritative outcomes and fallback

- `pending_resolution` is the sole result that preserves a supported pending
  context after an ordinary clarification. Its candidate set can only remain
  the same or narrow.
- `ready` remains persisted and executed through the existing ready-pending
  path. Its execution result clears or advances context under existing queue
  rules.
- A resolver-produced `rejected` is definitive: clear active pending state and
  context, return that rejected result once, and perform no mutation.
- An explicit deterministic status query is a read-only interruption: it
  reads only `session.id_pedido`, returns the existing status outcome, and
  leaves pending state, candidate sets, queue, and context byte-for-byte
  unchanged. It never invokes the classifier or an LLM.
- Unexpected technical failures continue to propagate to the caller-owned
  transaction and never become a successful response or a context cleanup.

## Transaction ownership and observability

The dispatcher, resolver, predicate, status query, event builder, and response
mapper SHALL not own commit, rollback, begin, close, refresh, or flush. The
existing transactional processor/provider coordinator commits successful turns
or rolls back technical failures. Context cleanup is only in-memory ORM state
within that outer transaction.

`pending_context_transition` is a versioned allowlisted operational event.
It may contain only a closed outcome, supported context kind, closed statuses,
candidate counts and a boolean indicating cleanup. Emission failure is best
effort and must not change the customer flow. The existing bounded production
CLI remains the sole allowed production-log reader.

## Expected files

- `backend/intents/orchestration/pending_context_dispatcher.py`
- A narrow deterministic status predicate colocated with the existing
  `backend/intents/orchestration/order_status_query.py`
- `backend/diagnostics/prompt_template.py` and
  `backend/diagnostics/intent_corpus.py`
- `backend/observability/events.py`, its public exports, and only the existing
  emission/query seams required for the new allowlisted event
- Focused pending-dispatch, product-selection E2E, status-query, prompt/corpus,
  observability-event and production-log CLI tests

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this
project's Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_pending_context_dispatcher.py backend/tests/test_pending_context_execution.py backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py backend/tests/test_order_status_query.py backend/tests/test_intent_classifier.py backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/pending_context_dispatcher.py backend/intents/orchestration/order_status_query.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/observability/events.py backend/observability/__init__.py backend/cli/query_production_logs.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_order_status_query.py backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/pending_context_dispatcher.py backend/intents/orchestration/order_status_query.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/observability/events.py backend/observability/__init__.py backend/cli/query_production_logs.py
openspec validate fix-pending-context-recovery-and-status-query --strict
```

## Rollback and deferred limitations

This is source-only and reversible by reverting the dispatcher interruption /
cleanup branch, prompt wording, and event registration. It does not alter
stored schema or records. Broader conversational interruption, automatic
context expiry, recovery of corrupted pending JSON, detailed business-reason
telemetry, dashboards, alerting, and production log inspection are deferred.

## Operational pause

Production-message verification for this change is paused while the separate
`add-pilot-order-operations-panel` change supplies a usable, authenticated
read-only view of pilot orders, sessions, and durable provider history. This
pause does not alter the completed source scope, authorize an archive, or
permit a manual database reset. After the panel is approved, implemented and
deployed, resume the production sequence below before considering this change
for closure.

## Handoff and archive gate

Once this correction is implemented and locally validated, it MUST be reviewed
and deployed through the normal approved path, then verified with controlled
real WhatsApp messages. The required production sequence is:

1. initial ambiguity → `Grande` → successful add;
2. a deliberate invalid clarification → one rejection and then a normal new
   message proves the failed context was cleared;
3. an explicit status question while a selection is pending → status response
   while the original pending candidates remain intact.

After those checks succeed, resume
`implement-product-line-observation-intent` for its own production-message
test. Only after that resumed change passes and the user explicitly approves
may the observation change be archived. Completion of this corrective change
is not permission to archive either change.
