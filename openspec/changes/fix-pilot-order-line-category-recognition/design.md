# Design: pilot order-line category recognition

## Decision

Extend the existing owned-order-line projection for `quitar_producto` with
the already persisted category description and ensure the one repository read
eager-loads that relationship. Do not modify the shared recognizer's token
rules or the hybrid decision policy.

```text
active session.id_pedido
  -> PedidoProductoService.list_by_pedido
  -> existing repository query eager-loads presentation -> product -> category
  -> quitar order-line catalog includes categoria_nombre from that row
  -> factory-selected fuzzy/hybrid recognizer sees `pizza` as category context
  -> only Mozzarella Grande / Chica own line IDs are returned as ambiguous
  -> existing initial orchestrator stores order_line_selection unchanged
```

## Why this boundary

The shared recognizer already knows how to disregard a category term when it
has a second, specific product token. Its commerce-catalog projection supplies
`categoria_nombre`; the order-line projection alone discarded it. Supplying
the same owned data restores the existing algorithm without a special phrase,
alias, threshold, semantic fallback, LLM decision or alternate recognition
pipeline.

The category is read through `PedidoProducto.producto_presentacion.producto
.categoria`, which belongs to the line already selected by the active
Pedido query. The repository shall eager-load it alongside product and
presentation to avoid an implicit per-row query. The recognizer continues to
own no direct SQLAlchemy statement and no catalog-wide lookup.

## Contracts and failure behavior

| Condition | Result |
| --- | --- |
| Two own lines share `Mozzarella`, category `Pizzas`, message contains `pizza` and `mozzarella` | Existing recognition returns only those two order-line IDs; initial flow remains `pending_resolution`. |
| One own line matches | Existing ready and handler path is unchanged. |
| Product exists in commerce but not this Pedido | No candidate is introduced; existing rejected result remains. |
| Category relation is absent/corrupt in an otherwise malformed row | No inferred category or candidate is invented; the existing normal failure/no-match semantics apply. |
| Hybrid semantic `unknown`/`ambiguous`/`unique` | Existing authoritative result is preserved; no fuzzy fallback is added. |
| ORM, service or recognition technical failure | Propagate to the caller-owned transaction; do not convert to a business match. |

`categoria_nombre` is recognition input only. It must not appear in a new
customer response, log, operational event or external contract.

## Ownership and safety

The repository query, service, recognizer and initial orchestrator are
read-only regarding transaction control: no commit, rollback, flush, begin,
close or refresh. `set_pending_intent` continues to stage the existing
pending state under the outer transaction only after the recognizer returns
the two valid owned line IDs. Candidate sets cannot be widened because the
recognizer starts and ends with the Pedido's own rows.

No new observability is necessary. The existing closed recognition observation
is sufficient to verify outcome category without storing message, customer,
Pedido, session, product, candidate or category data.

## Tests

- Repository surface test proves the existing list projection adds the product
  category eager-load without changing its service API or transaction behavior.
- Recognizer test uses real `FuzzyProductRecognizer` data for `Pizzas` /
  `Mozzarella Grande` / `Mozzarella Chica` plus an unrelated `Napolitana`
  line, and proves `pizza de mozzarella` produces exactly the two Mozzarella
  order-line IDs.
- Initial orchestration test proves the resulting two candidates create the
  existing `order_line_selection` pending state and does not execute a handler.
- Existing no-catalog-fallback, no-mutation, restricted-resolver and hybrid
  boundary tests remain in the focused command to prevent regression.

No production traffic, implementation, deploy, sync or archive is authorized
by this design.
