## ADDED Requirements

### Requirement: Initial agregar_producto orchestration function
The system SHALL export `process_initial_agregar_producto(db, session, source_text: str) -> ProcessedIntent` from `backend/intents/orchestration/agregar_producto_orchestrator.py`.

#### Scenario: Function is importable
- **WHEN** a module imports `process_initial_agregar_producto`
- **THEN** the import succeeds and the binding is callable

#### Scenario: Returned value is typed
- **WHEN** the orchestration function processes any input
- **THEN** it returns a valid `ProcessedIntent`

### Requirement: Initial processing pipeline
The orchestration function SHALL load the commerce-scoped product-presentation catalog through the existing service layer, call `detectar_productos(source_text, productos_presentaciones)`, normalize the result with `resolve_product_intent`, and build the typed intent with `process_agregar_producto`.

#### Scenario: Exact product produces ready intent
- **WHEN** the recognizer returns one confident product match
- **THEN** the orchestration returns a `ProcessedIntent` with `status == "ready"` and does not execute a handler

#### Scenario: Ambiguous product produces pending intent
- **WHEN** the recognizer returns multiple possible presentations
- **THEN** the orchestration returns a `ProcessedIntent` with `status == "pending_resolution"` and candidate IDs

### Requirement: Valid pending context persistence
When the processed intent is `pending_resolution` and `resolve_context_type` returns a context, the orchestration SHALL call `set_pending_intent(session, processed_intent)` and return the processed intent.

#### Scenario: Product selection context is stored
- **WHEN** an ambiguous product intent has valid candidate IDs and pending requirements
- **THEN** the session pending state contains the processed intent and `context_type == "product_selection"`

### Requirement: Invalid pending contexts are not persisted
When the processed intent is pending but `resolve_context_type` returns no context, the orchestration SHALL return it without calling `set_pending_intent` or modifying pending state.

#### Scenario: Unknown result is not stored
- **WHEN** recognition produces an intent with no valid pending context
- **THEN** the result is returned and no invalid pending intent is persisted

### Requirement: No handler or transaction side effects
The orchestration SHALL NOT commit, rollback, execute `agregar_producto`, create or modify `pedidos` or `pedidos_productos`, generate customer responses, or call FastAPI routers.

#### Scenario: Ready result remains unexecuted
- **WHEN** the first pass produces a ready intent
- **THEN** the handler is not called and the intent is returned directly

#### Scenario: Session transaction remains caller-owned
- **WHEN** the orchestration completes
- **THEN** it has not called `commit` or `rollback` on the supplied database session

### Requirement: Public surface is limited
The orchestration module SHALL export only `process_initial_agregar_producto` through `__all__` and SHALL not duplicate recognizer, resolver, processor, service, or repository logic.

#### Scenario: Single public orchestration symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["process_initial_agregar_producto"]`
