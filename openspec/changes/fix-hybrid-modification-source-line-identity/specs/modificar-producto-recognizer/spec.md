## MODIFIED Requirements

### Requirement: Source catalog scope

The recognizer SHALL build the source candidate catalog exclusively from
`PedidoProductoService.list_by_pedido(session.id_pedido)`. Catalog products
absent from the active draft Pedido SHALL NOT appear as source candidates.
When a configured product recognizer returns a source entry or ordinary
possible source entry with a `producto_presentacion_id`,
`modificar_producto_recognizer` SHALL recover `pedido_producto_id` only by an
exact lookup in that already-built current source catalog before flattening
`source_candidate_ids`. It SHALL not query, reload, infer or select a source
line outside that catalog.

#### Scenario: Hybrid unique source restores the exact own line identity

- **WHEN** the active draft contains a `PedidoProducto(id=41)` whose
  presentation id is `101`, and hybrid recognition returns one source entry
  with `producto_presentacion_id == 101` but no `pedido_producto_id`
- **THEN** the recognizer emits `source_candidate_ids == [41]`
- **AND THEN** the existing destination candidate IDs and extracted quantity
  remain unchanged

#### Scenario: Hybrid possible source preserves the restricted own candidates

- **WHEN** hybrid recognition returns possible source presentation IDs `101`
  and `102`, and the current source catalog maps them to own line IDs `41`
  and `42`
- **THEN** the recognizer emits exactly source candidates `41` and `42`
- **AND THEN** it does not add an unrelated current or historical Pedido line

#### Scenario: Foreign or unmapped source presentation remains absent

- **WHEN** a recognized source entry has no exact presentation match in the
  current source catalog, is malformed, or is a category-only group
- **THEN** it contributes no `source_candidate_ids`
- **AND THEN** the existing no-candidate outcome remains responsible for the
  no-mutation response
