## MODIFIED Requirements

### Requirement: Pedido producto service delegation

The handler SHALL use the pedido associated with `conversation_session.id_pedido` and delegate line consolidation to the existing `PedidoProductoService.add_or_increment`, passing `id_pedido`, `id_producto_presentacion`, and `cantidad`. It SHALL not accept or supply `precio_unitario` from the intent. When the service returns the consolidated `PedidoProducto` row, the handler SHALL preserve the original intent's `resolved_data`, `requirements`, and `candidate_ids`, and SHALL write the operation's outcome data into `resolved_data` under the keys `cantidad_agregada` (the integer quantity added in this operation, equal to the supplied `cantidad`), `cantidad_final` (the integer quantity on the consolidated line after the operation, equal to the row's persisted `cantidad`), and `linea_creada` (a boolean that is `True` when the service created a new row and `False` when the service incremented an existing row).

#### Scenario: Ready intent with no existing line creates one order line

- **WHEN** a valid ready intent and a conversation session with a draft pedido are provided, and the pedido contains no `PedidoProducto` row for the supplied `id_producto_presentacion`
- **THEN** the service creates one `PedidoProducto` for the correct pedido, presentation, and quantity using the current database price, and the handler returns an executed intent whose `resolved_data` carries `cantidad_agregada == cantidad`, `cantidad_final == cantidad`, and `linea_creada == True`

#### Scenario: Ready intent with an existing line increments the same order line

- **WHEN** a valid ready intent and a conversation session with a draft pedido are provided, and the pedido already contains a `PedidoProducto` row for the supplied `id_producto_presentacion`
- **THEN** the service increments that row's `cantidad` by the supplied value and preserves the original `precio_unitario` snapshot, and the handler returns an executed intent whose `resolved_data` carries `cantidad_agregada == cantidad`, `cantidad_final == (existing_cantidad + cantidad)`, and `linea_creada == False`

#### Scenario: Missing pedido is rejected

- **WHEN** the conversation session has no associated `id_pedido`
- **THEN** the handler returns `status == "rejected"` without creating or incrementing any line, and `resolved_data` is unchanged

## ADDED Requirements

### Requirement: Handler must not decide between insert and increment

The handler SHALL delegate the decision between inserting a new `PedidoProducto` row and incrementing an existing row to `PedidoProductoService.add_or_increment`. The handler SHALL NOT query `PedidoProducto` directly, SHALL NOT inspect `pedido_producto` rows from any repository, SHALL NOT branch on the existence of an existing line, and SHALL NOT commit or rollback the database transaction. The service is the sole owner of the consolidation logic.

#### Scenario: Handler does not query PedidoProducto directly

- **WHEN** the handler module source is inspected
- **THEN** it contains no import from `backend.repositories.pedido_producto_repository`, no `select(PedidoProducto)` statement, and no direct `session.get(PedidoProducto, ...)` call

#### Scenario: Handler does not commit or rollback

- **WHEN** the handler executes successfully or returns `rejected` / `failed`
- **THEN** the SQLAlchemy session passed to the handler does not have `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin` invoked by the handler body

### Requirement: Successful execution preserves intent data and threads result data into resolved_data

After successful service delegation, the handler SHALL return a new `ProcessedIntent` with `status == "executed"`. The returned intent SHALL preserve the original `intent`, `source_text`, `recognizer`, `handler`, `requirements`, and `candidate_ids` fields. The returned intent's `resolved_data` SHALL be the input's `resolved_data` updated with `cantidad_agregada`, `cantidad_final`, and `linea_creada` so the response builder can render the executed confirmation without re-querying the database.

#### Scenario: Successful execution carries result data

- **WHEN** the order line is created or incremented successfully
- **THEN** the returned intent has `status == "executed"`, the original `resolved_data` keys (`producto_presentacion_id`, `cantidad`) are preserved, and three new keys are present: `cantidad_agregada` (the integer quantity added in this operation), `cantidad_final` (the integer quantity on the consolidated line after the operation), and `linea_creada` (a boolean)