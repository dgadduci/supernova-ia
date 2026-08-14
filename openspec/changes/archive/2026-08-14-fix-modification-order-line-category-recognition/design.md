# Design: category context for modification source recognition

## Decision

Mirror the already deployed `quitar_producto` owned-line projection only at
the corresponding source-catalog boundary in `modificar_producto`:

```text
PedidoProductoService.list_by_pedido
  -> existing eager load: presentation -> product -> category
  -> modificar source catalog: categoria_nombre=producto.categoria.descripcion
  -> existing factory-selected recognizer
  -> existing own-presentation to own-order-line identity projection
  -> existing initial/resolver/handler flow
```

No repository change is expected because `list_by_pedido` already eager-loads
`Producto.categoria`. The implementation must not add a direct query,
catalog-wide lookup, category candidate list, phrase special case, or new
recognition pipeline.

## Safety invariants

- Every candidate still originates in the active `session.id_pedido` lines.
- `categoria_nombre` provides token context only; it never supplies an ID or
  chooses a line.
- The existing identity projection maps only a recognized presentation ID
  found in that same source catalog to its current `pedido_producto_id`.
- Multiple valid own source lines retain the existing restricted
  `source_selection` pending behavior; zero remains zero.
- Destination candidates, quantities, quantity-invalid rejection, response
  mapping, and caller-owned transaction semantics remain untouched.
- Missing/malformed category data does not trigger guessed aliases or a
  global-catalog fallback.

## Test strategy

- Catalog unit coverage: category description is copied from the already
  related own line and no separate repository call is introduced.
- Recognizer coverage using the shared recognizer boundary: `pizza de
  mozzarella grande` resolves only the matching owned line; `pizza de
  mozzarella` returns precisely the two owned Mozzarella lines, excluding an
  unrelated Pizza line; `empanada de verdura` resolves only its own line.
- Initial or end-to-end coverage: category-qualified source combined with a
  valid destination uses existing ready/pending semantics, has no transaction
  control in recognizer/orchestrator, and never mutates before the handler.
- Negative coverage: a category-qualified product absent from the draft
  produces no source candidate and preserves all lines.

## Failure behavior

This is a projection-only repair. Existing recognition outcomes and safe
fallbacks retain their meaning: a real no-match stays rejected, ambiguity
stays pending only over owned candidate IDs, and technical failures propagate
to the caller-owned transaction rather than becoming a guessed match.
