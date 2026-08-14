## MODIFIED Requirements

### Requirement: Catalog is limited to current order lines

The recognizer SHALL build the candidate catalog from
`PedidoProductoService.list_by_pedido(session.id_pedido)` and SHALL NOT call
any catalog-wide product query. Each catalog entry SHALL carry
`pedido_producto_id`, `producto_presentacion_id`, the product name, the
owned product category description as `categoria_nombre`, the presentation
code, the presentation description, and the current `cantidad`. The category
description is only a token-context field for the shared recognizer; it SHALL
not widen the candidate universe beyond those PedidoProducto rows.

#### Scenario: Category term preserves a specific own-product ambiguity

- **WHEN** the active draft contains `Mozzarella Grande`, `Mozzarella Chica`
  and an unrelated `Napolitana Chica`, all in the `Pizzas` category, and the
  customer asks to remove `una pizza de mozzarella`
- **THEN** recognition returns exactly the two Mozzarella
  `pedido_producto_id` values as possible candidates
- **AND** it does not return the Napolitana line or any commerce-catalog line

#### Scenario: Category is loaded through the existing line query

- **WHEN** the recognizer loads order lines for a non-empty draft
- **THEN** the existing repository list projection eager-loads the product
  category alongside product and presentation
- **AND** the recognizer executes no direct SQLAlchemy query and does not
  trigger a category query per line

### Requirement: No catalog fallback

The recognizer SHALL NOT search the global commerce catalog, the
categoria_productos table, or the presentaciones table as an independent
candidate source. It MAY use the category already eager-loaded from each
active draft Pedido line solely as token context. If the recognizer cannot
resolve the message to one of those lines, it SHALL return a result with no
recognized candidate.

#### Scenario: Category context does not introduce a different line

- **WHEN** the message contains a category term and a product absent from the
  active draft but present in the commerce catalog
- **THEN** no candidate outside the active draft lines is returned
