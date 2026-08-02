## ADDED Requirements

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
The handler SHALL use the pedido associated with `conversation_session.id_pedido` and delegate line creation to the existing `PedidoProductoService`, passing only `id_pedido`, `id_producto_presentacion`, and `cantidad`. It SHALL not accept or supply `precio_unitario` from the intent.

#### Scenario: Ready intent creates one order line
- **WHEN** a valid ready intent and conversation session with a draft pedido are provided
- **THEN** the service creates one `PedidoProducto` for the correct pedido, presentation, and quantity using the current database price

#### Scenario: Missing pedido is rejected
- **WHEN** the conversation session has no associated `id_pedido`
- **THEN** the handler returns `status == "rejected"` without creating a line

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
