# Proposal: distinct source and destination quantities for product modification

## Why

The pilot message `cambiar dos napolitanas grandes por una pizza de
mozzarella` currently transfers two source units and creates/increments two
destination units. This is not a panel defect: `modificar_producto` extracts
one `cantidad` (the first number) and the atomic service uses it for both
sides. The persisted order and response therefore implement the old,
single-quantity contract, but not the explicit `2 -> 1` request.

## What Changes

- Recognize an explicit positive quantity independently on each side of the
  existing `por` boundary for `modificar_producto`.
- Carry an optional destination quantity through initial orchestration and
  pending source/destination selection without widening candidates.
- Atomically decrement the requested source quantity and create/increment the
  requested destination quantity; preserve legacy one-quantity behavior.
- Render an executed response whose two quantities match the durable mutation
  when they differ.

## Objective and current execution path

```text
cambiar dos napolitanas grandes por una pizza de mozzarella
  -> recognizer extracts one global cantidad = 2
  -> source and destination resolve (or destination becomes pending)
  -> handler calls modify_product(..., cantidad=2)
  -> service decrements 2 and increments 2
  -> response says 2 por 2
```

The corrected path recognizes `cantidad=2` (source) and
`cantidad_destino=1`, carries both through any pending clarification, and
performs one caller-owned atomic operation: decrement 2 / increment 1.

## Scope and non-goals

Scope is one `modificar_producto` message with an explicit positive quantity
on both sides of the existing `por` separator, including destination
clarification before execution.

Backward compatibility is mandatory:

- no quantity: transfer the whole current source quantity to destination;
- exactly one explicit quantity: retain the existing equal-quantity transfer;
- persisted pending intents created before this change and carrying only
  legacy `cantidad` continue with that same equal-quantity behavior.

Non-goals: product/line recognition policy, classifier/prompt vocabulary,
hybrid/fuzzy activation, candidate ranking, catalog scope, quantity words
outside the existing extractor vocabulary, ratios, prices/totals, splitting
one source into multiple destinations, migrations, panel layout, provider or
Twilio behavior. A message with only a destination-side quantity but no
explicit source quantity retains existing one-quantity semantics; this change
does not infer an exchange ratio.

## Shared boundary and outcomes

`por` remains the sole source/destination boundary. The recognizer derives
both values deterministically from the normalized side texts; no LLM or hybrid
output is an authority for quantities or mutations. The source quantity is
authoritative for the ceiling check; the destination quantity is authoritative
only for the bounded destination increment/create.

| Condition | Required outcome |
| --- | --- |
| Explicit positive quantity on both sides | Preserve both quantities; decrement source by origin and increment destination by destination. |
| One or zero explicit quantities | Existing equal-quantity/full-source behavior, unchanged. |
| Non-positive or malformed explicit quantity | Existing deterministic rejection; no order mutation. |
| Source request exceeds current source quantity | Existing `quantity_exceeds_source`; no mutation. |
| Destination ambiguity | Persist both quantities unchanged; resolution may only select existing pending candidates. |
| Destination unavailable, foreign, missing price, or technical failure | Existing rejection/propagation; no partial mutation. |

## Transaction ownership, privacy, and observability

Recognizers, orchestrators, resolvers, handlers, and responses remain
caller-owned: no commit, rollback, begin, or independent transaction is
introduced. The service validates both sides before the first source mutation
and retains the one-transaction source/decrement + destination/increment
operation. No IDs, raw pending JSON, source text, customer data, or quantity
diagnostics are added to the pilot panel, events, or logs.

## Expected files

- `backend/intents/recognizers/modificar_producto_recognizer.py`
- `backend/intents/orchestration/modificar_producto_initial.py`
- `backend/intents/context/product_modification_resolver.py`
- `backend/intents/handlers/modificar_producto_handler.py`
- `backend/services/modification_result.py`
- `backend/services/pedido_producto_service.py`
- `backend/intents/responses/modificar_producto_response.py`
- smallest relevant existing modificar-producto unit/integration tests
- `openspec/changes/fix-product-modification-distinct-source-destination-quantities/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_handler.py backend/tests/test_pedido_producto_service.py backend/tests/test_modificar_producto_response.py backend/tests/test_modificar_producto_end_to_end.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/modificar_producto_recognizer.py backend/intents/orchestration/modificar_producto_initial.py backend/intents/context/product_modification_resolver.py backend/intents/handlers/modificar_producto_handler.py backend/services/modification_result.py backend/services/pedido_producto_service.py backend/intents/responses/modificar_producto_response.py backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_handler.py backend/tests/test_pedido_producto_service.py backend/tests/test_modificar_producto_response.py backend/tests/test_modificar_producto_end_to_end.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/modificar_producto_recognizer.py backend/intents/orchestration/modificar_producto_initial.py backend/intents/context/product_modification_resolver.py backend/intents/handlers/modificar_producto_handler.py backend/services/modification_result.py backend/services/pedido_producto_service.py backend/intents/responses/modificar_producto_response.py
openspec validate fix-product-modification-distinct-source-destination-quantities --strict
git diff --check
```

## Rollback, pilot gate, and deferred limitations

The change is source-only and reversible by removing the paired-quantity path;
legacy `cantidad` remains supported for persisted pending contexts. After an
approved deploy, test in a clean local pilot draft: `cambiar dos napolitanas
grandes por una pizza de mozzarella` followed, if needed, by `chica`. Verify
the source decreases by 2, the chosen destination increases by 1, the response
states 2 and 1, pending/context clear, and unrelated one-quantity/full-source
modifications remain unchanged. Do not archive this or the dependent pending-
destination change without explicit user approval.
