## ADDED Requirements

### Requirement: Pending context execution function
The system SHALL export `execute_ready_pending_context(db: DatabaseSession, session: ConversationSession) -> ProcessedIntent` from `backend/intents/orchestration/pending_context_execution.py`.

#### Scenario: Function is importable
- **WHEN** a module imports `execute_ready_pending_context`
- **THEN** the import succeeds and the binding is callable

### Requirement: Active ready intent validation
The function SHALL load pending state through `PendingIntentService`, require an active intent, and require `active.status == "ready"` before handler execution.

#### Scenario: Missing active intent is rejected
- **WHEN** pending state has no active intent
- **THEN** the function returns a rejected `ProcessedIntent` without handler execution or context cleanup

#### Scenario: Non-ready active intent is rejected
- **WHEN** the active intent status is not `ready`
- **THEN** the function returns a rejected copy and leaves pending context unchanged

### Requirement: Agregar producto dispatch
The function SHALL dispatch only active intents whose `handler == "agregar_producto"` to `execute_agregar_producto(db, session, active)`.

#### Scenario: Ready agregar_producto is executed
- **WHEN** a ready active intent has handler `agregar_producto`
- **THEN** the function delegates exactly once to the agregar-producto handler

#### Scenario: Unsupported handler is rejected
- **WHEN** a ready active intent names another handler
- **THEN** the function returns a rejected copy without handler execution

### Requirement: Successful context cleanup
When handler execution returns `status == "executed"`, the function SHALL call `clear_pending_context(session)`, clearing pending intents and setting context type to `None`, then return the executed intent.

#### Scenario: Executed result clears context
- **WHEN** the agregar-producto handler returns an executed intent
- **THEN** pending state is cleared, context type becomes `None`, and the executed intent is returned

### Requirement: Failed or rejected context preservation
When handler execution returns `rejected` or `failed`, the function SHALL return that intent without clearing or modifying pending context.

#### Scenario: Rejected result preserves context
- **WHEN** the handler returns a rejected intent
- **THEN** the original pending intents and context type remain unchanged

#### Scenario: Failed result preserves context
- **WHEN** the handler returns a failed intent
- **THEN** the original pending intents and context type remain unchanged

### Requirement: Execution orchestration boundaries
The function SHALL reuse `load`, `clear_pending_context`, and `execute_agregar_producto`; it SHALL not perform SQLAlchemy queries, repository access, commits, rollback, HTTP concerns, response generation, queue promotion, handler changes, or recognizer changes.

#### Scenario: No transaction or infrastructure side effects
- **WHEN** the function completes any path
- **THEN** it has not committed, rolled back, queried repositories, generated responses, or promoted a queue

### Requirement: Public surface is limited
The module SHALL export only `execute_ready_pending_context` through `__all__` and SHALL not introduce a generic context dispatcher.

#### Scenario: Single public execution symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["execute_ready_pending_context"]`
