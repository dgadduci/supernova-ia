## MODIFIED Requirements

### Requirement: Modification source catalog is limited to current order lines

The `modificar_producto` recognizer SHALL build its source catalog only from
`PedidoProductoService.list_by_pedido(session.id_pedido)`. Each source row
SHALL carry its `pedido_producto_id`, `producto_presentacion_id`, product
name, already eager-loaded product category description as `categoria_nombre`,
presentation code, presentation description, and current quantity. The
category description is token context only and SHALL NOT widen the candidate
universe beyond those PedidoProducto rows.

#### Scenario: Category-qualified specific source resolves an owned line

- **WHEN** the active draft contains `Mozzarella Grande` in category `Pizzas`
- **AND** the customer requests `cambia una pizza de mozzarella grande por 1 empanada de pollo`
- **THEN** source recognition returns only that own `pedido_producto_id`
- **AND** no commerce-catalog order line is introduced.

#### Scenario: Category-qualified source ambiguity stays restricted

- **WHEN** the active draft contains `Mozzarella Grande`, `Mozzarella Chica`,
  and unrelated `Napolitana Chica`, all in category `Pizzas`
- **AND** the customer requests `cambia una pizza de mozzarella por una empanada de pollo`
- **THEN** source recognition returns exactly the two own Mozzarella line IDs
- **AND** the existing `source_selection` pending flow owns clarification.

#### Scenario: Category context does not create a source line

- **WHEN** a category-qualified source product exists in the commerce catalog
  but is absent from the active draft
- **THEN** source recognition returns no candidate
- **AND** the existing source-absent rejection preserves the Pedido.

### Requirement: Source category projection is read-only

The source category projection SHALL reuse the category relationship already
loaded by the existing order-line query. It SHALL NOT issue a catalog-wide or
per-line category query, own transaction control, or alter destination and
quantity recognition.

#### Scenario: Missing category relation fails safely

- **WHEN** an otherwise malformed order-line row has no usable category
  description
- **THEN** the recognizer does not invent category context or a candidate
- **AND** retains the existing no-match or technical-failure behavior.
