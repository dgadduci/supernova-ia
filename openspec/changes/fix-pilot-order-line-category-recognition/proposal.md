# Proposal: fix pilot order-line category recognition

## Objective

Restore the expected own-order-line ambiguity for a customer request such as
`Quiero quitar una pizza de mozzarella` when the active draft contains
`Mozzarella Grande` and `Mozzarella Chica`. The request SHALL create the
existing restricted `order_line_selection` pending context instead of being
rejected as absent.

## Current execution path and evidence

Initial dispatch classifies the request as `quitar_producto` and calls
`process_initial_quitar_producto`. Its recognizer loads only the active
Pedido's `PedidoProducto` rows through `PedidoProductoService.list_by_pedido`,
projects them to the shared factory-bound recognizer, converts recognized
presentation IDs back to `pedido_producto_id`s, and returns pending resolution
for multiple rows.

The deployed trace for the reported turn records the configured authoritative
hybrid decision as `unknown`; the customer response is the existing
`quitar_producto` no-candidate rejection. The order-line projection currently
sets `categoria_nombre` to `None`, while the shared fuzzy-side key-token guard
treats `pizza` as a required product-name token unless it is known as the
row's category. For a line whose product name is `Mozzarella` and category is
`Pizzas`, the guard removes neither token and returns no fuzzy candidates;
the hybrid boundary then correctly returns `unknown` under its existing
contract. This is a missing owned-catalog field, not a calibration, price,
pending-dispatch, or session-state failure.

## Scope

- Eager-load the already related category as part of the existing
  `PedidoProductoRepository.list_by_pedido` read projection.
- Project the owned row's category description as `categoria_nombre` in the
  `quitar_producto` order-line recognizer.
- Prove the real shared recognizer maps the Pizza/Mozzarella own-order
  catalog to exactly the two own Mozzarella line candidates and initial
  orchestration persists the existing pending context.
- Add focused repository, recognizer and orchestration coverage for the
  category-aware projection and no-mutation boundaries.

## Non-goals

- No hybrid/fuzzy mode, policy, threshold, vector, embedding, alias, prompt,
  classifier, LLM, catalog-wide fallback, candidate widening, response-text,
  handler, transaction, schema, migration, endpoint, panel, deploy, sync or
  archive change.
- No change to `modificar_producto` or another recognizer merely because it
  contains a similar projection; this production defect is limited to the
  observed `quitar_producto` flow.
- No raw customer text, identifiers, catalog labels, prices or exception
  material in new observability. Existing closed `shadow_product_recognition`
  remains the operational evidence surface.

## Authoritative outcomes and fallback

- The active session's own draft Pedido lines remain the only authoritative
  candidate universe. The category is a descriptive field of those same rows;
  it cannot introduce a line from another Pedido or commerce.
- A request matching two owned `Mozzarella` presentations yields exactly those
  two `pedido_producto_id`s and the existing `pending_resolution` outcome.
- A unique owned-line match continues to use the existing ready/handler path;
  a true no-match continues to return the current safe rejected outcome.
- Hybrid `unknown`, `ambiguous`, and `unique` retain their existing semantics.
  This change SHALL NOT add a fallback from a semantic hybrid decision to
  fuzzy, nor make an LLM an authority for a mutation.
- Unexpected load/ORM/recognition failures continue to propagate to the outer
  transaction owner; they SHALL NOT become a match, context cleanup, or a
  customer-success response.

## Transaction ownership and observability

The repository remains a read-only query collaborator. The repository,
service, recognizer and initial orchestration SHALL NOT commit, rollback,
flush, begin, close or otherwise own the caller transaction. The recognizer
does not emit a new event; it continues to use the shared configured
recognition boundary, whose existing closed observation contains no customer
or order data.

## Expected files

- `backend/repositories/pedido_producto_repository.py`
- `backend/intents/recognizers/quitar_producto_recognizer.py`
- `backend/tests/test_pedido_producto_service_surface.py`
- `backend/tests/test_quitar_producto_recognizer.py`
- `backend/tests/test_quitar_producto_initial.py`
- `openspec/changes/fix-pilot-order-line-category-recognition/specs/quitar-producto-recognizer/spec.md`

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this project's
Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_pedido_producto_service_surface.py backend/tests/test_quitar_producto_recognizer.py backend/tests/test_quitar_producto_initial.py backend/tests/test_quitar_producto_end_to_end.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_controlled_hybrid_product_recognition.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/repositories/pedido_producto_repository.py backend/intents/recognizers/quitar_producto_recognizer.py backend/tests/test_pedido_producto_service_surface.py backend/tests/test_quitar_producto_recognizer.py backend/tests/test_quitar_producto_initial.py backend/tests/test_quitar_producto_end_to_end.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_controlled_hybrid_product_recognition.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/repositories/pedido_producto_repository.py backend/intents/recognizers/quitar_producto_recognizer.py
openspec validate fix-pilot-order-line-category-recognition --strict
```

## Rollback, production gate and dependent work

This source-only change is reversible by reverting the category eager-load and
the one catalog projection. It does not modify persisted data. After an
approved deployment, start from the current active draft and send only the
controlled `Quiero quitar una pizza de mozzarella` turn. Confirm the existing
clarification names the two Mozzarella lines and no line is changed. Then send
`Napolitana chica` to exercise the already-approved definitive-rejection
cleanup, confirm all three lines remain unchanged, and send the existing
explicit status question to prove initial dispatch resumed.

Only when that production gate succeeds may
`fix-pending-context-recovery-and-status-query` resume its remaining gate and
then `implement-product-line-observation-intent` resume its own production
test. No active change may be archived without explicit user approval.
