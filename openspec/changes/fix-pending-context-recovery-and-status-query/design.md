# Design: pending-context recovery and status query

## Decision

Keep the product-selection architecture and add two narrow dispatcher rules:

```text
active supported context
  -> explicit local status predicate? -> own-pedido status read; preserve context
  -> otherwise existing resolver over persisted candidates
       -> pending: persist/refine
       -> ready: existing execution
       -> rejected: clear active + context, return rejected once
```

The LLM remains absent from the pending path. The only interruption is a
closed local grammar for an explicit status question, a read-only operation
whose ownership boundary is already implemented by `order_status_query`.

## Selection and cleanup

`Grande` uses the existing presentation-alias resolver against the persisted
candidate IDs. The test fixture shall provide the same two candidates exposed
to the customer (`Mozzarella Grande`, `Mozzarella Chica`), assert that
`Grande` reaches `ready`, then the existing add handler reaches `executed` and
clears the active state/context. It must prove no full commerce catalog lookup
or candidate introduction occurs.

For any supported context resolver returning `rejected`, the dispatcher first
persists no rejected active state, instead clearing the pending JSON and
setting `session.context_type = None`, then returns the rejected outcome. This
is a definitive business result, not a technical failure. `pending_resolution`
retains current behavior; `failed` is not converted to cleanup.

## Explicit status interruption

Add a pure `is_explicit_order_status_query(text)` alongside the existing status
orchestrator. It normalizes accents, case, punctuation and whitespace, then
accepts only a closed Spanish set equivalent to:

- `estado de mi pedido`
- `cual es el estado de mi pedido`
- `como va mi pedido`
- `donde esta mi pedido`

No product name, quantity, confirmation, cancellation, delivery, greeting or
free-form phrase qualifies. When true while one of the existing supported
pending contexts is active, the dispatcher invokes
`process_initial_order_status_query(db, session, message)` directly. It does
not call the classifier, resolver, pending-state persistence helper, handler,
or response builder. The returned status intent is mapped through the existing
mapper. Its valid `executed` and business `rejected` results preserve the
active pending state and context exactly; technical exceptions propagate.

The static classifier prompt changes only its status sentence to state that a
customer may ask for the status of the current pedido, including a draft. The
controlled corpus pins `Cuál es el estado de mi pedido` to
`consultar_estado_pedido`; this governs the normal no-context path, not the
pending interruption.

## Safe trace contract

Extend `backend.observability.events` rather than creating a logger or
parallel telemetry path. The new `pending_context_transition` event has
component `pending_context` and exactly these business fields in addition to
the standard event envelope:

| Field | Closed values / bounds |
|---|---|
| `outcome` | `pending_preserved`, `ready_executed`, `rejected_cleared`, `status_interrupted` |
| `context_kind` | `product_selection`, `order_line_selection`, `product_modification`, `order_clear_confirmation` |
| `status_before`, `status_after` | processed-intent statuses from a fixed allowlist |
| `candidate_count_before`, `candidate_count_after` | integer 0–200 |
| `context_cleared` | boolean |

The event intentionally has no identifiers, source text, catalog/product
labels, request/response content, LLM information, exception material, or
correlation field. The catalogue validates and parses the fields; the existing
bounded query CLI receives it automatically through that catalogue. Event
emission is best effort and uses existing safe failure handling.

## Tests

Tests shall cover:

- end-to-end `Mozzarella` ambiguity → `Grande` → executed add and cleared
  context;
- a pending resolver `rejected` leaves no active intent/context, and the next
  ordinary input reaches initial dispatch rather than the stale resolver;
- status query with product selection and order-line selection pending returns
  the status response while candidate IDs, queue, and context are unchanged;
- status after definitive rejection reaches the normal classifier/dispatcher
  path and reports the own draft pedido status;
- deterministic predicate false positives; prompt/corpus exact fixture;
- event construction/parsing, rejected cleanup/status interruption emission,
  allowlist rejection for PII-like or unknown fields, and no changed business
  result if emission fails.

No production traffic or test execution is authorized by this design. The
post-merge production verification remains the explicit user-controlled gate
in `proposal.md`.
