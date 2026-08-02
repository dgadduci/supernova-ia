# Agregar Producto Handler Specification

## Purpose

Provide a business-action handler that consumes ready `agregar_producto` intents from the orchestration layer and creates one `PedidoProducto` through the existing `PedidoProductoService`, translating expected rule failures into rejected status, unexpected failures into failed status, and successful creation into executed status — without owning database access, HTTP responses, context cleanup, or queue promotion.
## Requirements
### Requirement: Agregar producto handler function
The system SHALL export `execute_agregar_producto(db: DatabaseSession, conversation_session: ConversationSession, intent: ProcessedIntent) -> ProcessedIntent` from `backend/intents/handlers/agregar_producto_handler.py`.

#### Scenario: Handler is importable
- **WHEN** a module imports `execute_agregar_producto`
- **THEN** the import succeeds and the binding is callable

### Requirement: Ready intent validation
The handler SHALL accept execution only when `intent.intent == "agregar_producto"`, `intent.status == "ready"`, `intent.handler == "agregar_producto"`, and `resolved_data` contains `producto_presentacion_id` and `cantidad`.

#### Scenario: Non-ready or wrong intent is rejected
- **WHEN** the handler receives an intent with an invalid intent name, handler name, status, or missing resolved field
- **THEN** it returns a new intent with `status == "rejected"` without creating an order line

### Requirement: Resolved value validation
The handler SHALL require an integer `producto_presentacion_id` and an integer `cantidad` greater than zero. Invalid values SHALL return a rejected intent preserving the original intent fields.

#### Scenario: Invalid quantity is rejected
- **WHEN** `cantidad` is missing, non-integer, or less than one
- **THEN** the handler returns `status == "rejected"` without invoking the order-line service

#### Scenario: Invalid presentation ID is rejected
- **WHEN** `producto_presentacion_id` is missing or not an integer
- **THEN** the handler returns `status == "rejected"` preserving resolved data and requirements

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

### Requirement: Successful execution result
After successful service delegation, the handler SHALL return a new `ProcessedIntent` with `status == "executed"` and the original intent, source text, recognizer, handler, resolved data, requirements, and candidate IDs preserved.

#### Scenario: Successful execution preserves intent data
- **WHEN** the order line is created successfully
- **THEN** the returned intent has `status == "executed"` and all other intent fields equal the input

### Requirement: Business failure handling
Expected business-rule failures SHALL return `status == "rejected"`; unexpected technical failures MAY return `status == "failed"`. The handler SHALL not silently swallow exceptions or translate errors into `HTTPException`.

#### Scenario: Non-draft pedido is rejected
- **WHEN** the associated pedido violates the existing draft-pedido business rule
- **THEN** the handler returns `status == "rejected"` through the existing service behavior

### Requirement: Handler boundaries
The handler SHALL not perform SQLAlchemy queries, access repositories directly, call FastAPI routers, generate responses, clear pending context, promote queues, commit, or rollback unless a reused service owns that transaction.

#### Scenario: Context state is preserved
- **WHEN** the handler executes successfully
- **THEN** `pending_intents` and `context_type` remain unchanged

#### Scenario: Handler has no HTTP or database implementation
- **WHEN** the handler source is inspected
- **THEN** it contains no SQLAlchemy query, repository access, router call, or response generation

### Requirement: Public surface is limited
The handler module SHALL export only `execute_agregar_producto` through `__all__` and SHALL not add a generic handler abstraction.

#### Scenario: Single public handler symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["execute_agregar_producto"]`

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

