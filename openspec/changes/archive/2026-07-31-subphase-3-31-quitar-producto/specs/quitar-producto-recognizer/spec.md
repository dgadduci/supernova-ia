# Capability: quitar-producto-recognizer

Provide a recognizer adapter for `quitar_producto` that builds its catalog exclusively from the active draft Pedido's current `PedidoProducto` rows, detects a matching order line and an optional quantity, and never falls back to catalog-wide product discovery.

## ADDED Requirements

### Requirement: Quitar producto recognizer module location

The system SHALL expose `recognize_quitar_producto` from `backend/intents/recognizers/quitar_producto_recognizer.py`.

#### Scenario: Recognizer is importable
- **WHEN** a module executes `from backend.intents.recognizers.quitar_producto_recognizer import recognize_quitar_producto`
- **THEN** the import succeeds and the binding is callable

### Requirement: Recognizer signature

The system SHALL expose `recognize_quitar_producto(db: DatabaseSession, session: ConversationSession, message: str) -> RecognizerResult` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model.

#### Scenario: Function is callable with the documented signature
- **WHEN** a caller invokes `recognize_quitar_producto(db, session, "quitá 2 empanadas de carne")`
- **THEN** the function returns a `RecognizerResult` without raising for a well-formed draft pedido

### Requirement: Catalog is limited to current order lines

The recognizer SHALL build the candidate catalog from `PedidoProductoService.list_by_pedido(session.id_pedido)` and SHALL NOT call any catalog-wide product query. Each catalog entry SHALL carry `pedido_producto_id`, `producto_presentacion_id`, the product name, the presentation code, the presentation description, and the current `cantidad`.

#### Scenario: Catalog reflects only the draft pedido
- **WHEN** the recognizer runs against a draft pedido with three `PedidoProducto` rows
- **THEN** the catalog has exactly those three entries and no other products appear

#### Scenario: Empty draft pedido yields an empty catalog
- **WHEN** the draft pedido has zero `PedidoProducto` rows
- **THEN** the catalog is empty and the recognizer returns a result with no recognized candidate

### Requirement: Quantity extraction

When the user message includes an explicit positive integer quantity, the recognizer SHALL set `quantity` to that integer. When the message omits a quantity, the recognizer SHALL set `quantity` to `None`.

#### Scenario: Explicit quantity is extracted
- **WHEN** the message contains `quitá 2 empanadas de carne`
- **THEN** the recognizer result has `quantity == 2`

#### Scenario: Missing quantity yields None
- **WHEN** the message contains `sacá la pizza grande` and no quantity
- **THEN** the recognizer result has `quantity is None`

### Requirement: No catalog fallback

The recognizer SHALL NOT search the global commerce catalog, the categoria_productos table, or the presentaciones table. If the recognizer cannot resolve the message to one of the catalog entries built from the draft pedido, it SHALL return a result with no recognized candidate.

#### Scenario: Valid commerce product absent from pedido is not found
- **WHEN** the message names a product that exists in the catalog but is not in the draft pedido
- **THEN** the recognizer result has no recognized candidate and no pedido_producto_id appears

#### Scenario: Inactive catalog product still in pedido is found
- **WHEN** the draft pedido contains a line whose underlying presentation is `activo=False`
- **THEN** the recognizer still surfaces the line as a candidate

### Requirement: Recognizer boundaries

The recognizer SHALL NOT execute SQLAlchemy statements directly; it SHALL delegate catalog construction to `PedidoProductoService.list_by_pedido` and SHALL NOT mutate `session`, the `PedidoProducto` rows, the `Pedido`, or any persisted state.

#### Scenario: Recognizer does not mutate session or pedido
- **WHEN** `recognize_quitar_producto(db, session, message)` completes
- **THEN** `session.id_pedido`, `session.context_type`, `session.pending_intents`, and every `PedidoProducto` field equal the values they had before the call

#### Scenario: Recognizer uses the service, not the repository
- **WHEN** the recognizer source is inspected
- **THEN** it imports `PedidoProductoService` (or a typed projection of it) and does NOT import `PedidoProductoRepository` directly
