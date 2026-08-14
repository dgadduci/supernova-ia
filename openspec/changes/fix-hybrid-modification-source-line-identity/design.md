# Design: hybrid modification source-line identity

## Decision

Keep `HybridAuthoritativeProductRecognizer` generic. It is correct for that
boundary to select only a `producto_presentacion_id`; an order-line primary key
is meaningful only to a Pedido-scoped caller. Repair the missing translation
in `modificar_producto_recognizer`, immediately after it recognizes against
the source catalog it has already built.

```text
current PedidoProducto rows
  -> source catalog: { producto_presentacion_id, pedido_producto_id, ... }
  -> existing hybrid/fuzzy recognition: presentation IDs only
  -> exact local projection: presentation ID -> own pedido_producto_id
  -> existing source_candidate_ids flattening
  -> existing resolver / handler / atomic service
```

The projection shall decorate recognized entries and ordinary possible-group
entries only. Category groups retain their existing shape. It maps only a
presentation ID that occurs in the current source catalog, and it must leave
unmapped results without `pedido_producto_id`.

## Boundaries and failure behavior

- The current `PedidoProductoService.list_by_pedido(session.id_pedido)` result
  is the complete source universe. No commerce-wide lookup, new query, or
  historical Pedido line may be used.
- `pedido_producto_id` remains distinct from destination
  `producto_presentacion_id`; the two candidate lists are never combined.
- Mapping does not alter source presentation IDs, recognition confidence,
  ranking, quantity, decision, pending stage or destination candidates.
- For absent, malformed, foreign, category-only or unmapped source entries,
  the existing flattening result remains empty. The current safe rejection or
  pending fallback owns the outcome; there is no guessed line.
- Fuzzy technical fallback remains a hybrid concern. Once it returns its
  normal result, the same source-local mapping may recover identity from a
  matching own presentation, without modifying fallback semantics.
- The recognizer executes no transaction method. Existing orchestration,
  handler and service retain mutation ownership.

## Tests

- A focused recognizer test supplies hybrid-shaped source output carrying only
  `producto_presentacion_id`; it must produce exactly the matching own
  `pedido_producto_id` and preserve a distinct destination ID.
- An ambiguous hybrid-shaped source group maps only its exact own lines; a
  foreign presentation, category group, malformed entry and missing mapping
  add no candidate and do not widen the source universe.
- A modification integration test injects the real
  `HybridAuthoritativeProductRecognizer` with deterministic embedding/vector
  collaborators and performs `cambiar 2 napolitanas grandes por 2
  napolitanas chicas`. Existing orchestration, handler and service must move
  exactly two, preserve line ownership and clear context through their normal
  path.
- Existing no-transaction and unchanged destination/error coverage remains
  focused; no live LLM call is required for deterministic regression proof.
