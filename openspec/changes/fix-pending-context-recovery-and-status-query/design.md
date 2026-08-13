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
| `outcome` | `pending_preserved`, `ready_executed`, `rejected_cleared`, `status_interrupted`, `invalid_state_cleared` |
| `context_kind` | supported context kinds; `none` / `unsupported` only for `invalid_state_cleared` |
| `status_before`, `status_after` | processed-intent statuses; `none` only as `status_before` for `invalid_state_cleared`, whose `status_after` is `rejected` |
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

## Production-regression amendment II: authoritative default quantity

`AGREGAR_PRODUCTO_CONTRACT` already declares `cantidad` required with default
`1`. The processor SHALL treat this non-null default as an authoritative,
deterministic business value when the recognizer omits quantity: it creates a
completed `RequirementState` with value `1` and retains that value in
`resolved_data`. A supplied quantity remains authoritative only when it is a
positive non-boolean integer; the existing validation/handler outcome governs
invalid supplied data and technical failures.

This happens at initial intent construction, before pending state is persisted.
It is therefore not a pending-resolver fallback and has no access to the
catalog, session, pedido, line, price, LLM, embeddings or hybrid score. The
processor owns no transaction method. Only the already-declared default is
used; no implicit quantity is introduced for other intent contracts.

```text
hybrid ambiguity with two restricted candidates, no quantity
  -> initial agregar_producto intent: cantidad=1 completed; presentation pending
  -> `Grande` resolves exactly one persisted candidate
  -> all required fields completed: ready
  -> existing pending execution and caller-owned product-add seam
```

The provider E2E shall patch only the product recognizer's first-turn result
to mimic the production shape (two candidate IDs, no `cantidad`) and leave the
second-turn resolver on its normal restricted catalog path. It must assert the
durable pending intent has completed quantity `1` before `Grande`; then assert
one line, a `Listo,` outbound response, a `ready_executed` pending event and a
`created` product-add event. Complementary unit tests shall pin explicit
quantity preservation and the directly affected smoke assertion shall no
longer claim that omitted default quantity is pending.
