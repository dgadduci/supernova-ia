## ADDED Requirements

### Requirement: Pending context dispatcher function
The system SHALL export `dispatch_pending_context(db: DatabaseSession, session: ConversationSession, message: str) -> ProcessedIntent` from `backend/intents/orchestration/pending_context_dispatcher.py`.

#### Scenario: Function is importable
- **WHEN** a module imports `dispatch_pending_context`
- **THEN** the import succeeds and the binding is callable

### Requirement: Active intent and context type validation
The dispatcher SHALL require an active intent from `PendingIntentService.load` and require `session.context_type` to be non-null before dispatching.

#### Scenario: Missing active intent is rejected
- **WHEN** pending state has no active intent
- **THEN** the dispatcher returns a rejected `ProcessedIntent` without modifying pending state

#### Scenario: Missing context type is rejected
- **WHEN** `session.context_type` is null
- **THEN** the dispatcher returns a rejected copy of the active intent without clearing context

### Requirement: Product selection dispatch
When `session.context_type == "product_selection"`, the dispatcher SHALL call the existing product-selection orchestration service with the supplied message and the active intent, then persist the resulting intent through `set_active`.

#### Scenario: Pending product selection reply persists context
- **WHEN** a `product_selection` reply still resolves to `pending_resolution`
- **THEN** the dispatcher persists the updated active intent and preserves context type

#### Scenario: Ready product selection triggers execution
- **WHEN** a `product_selection` reply resolves to `ready`
- **THEN** the dispatcher persists the ready intent and delegates to `execute_ready_pending_context`, returning the executed result

### Requirement: Unsupported or invalid context handling
The dispatcher SHALL reject unsupported or invalid context values by copying the active intent with `status == "rejected"` and SHALL NOT clear or modify pending context.

#### Scenario: Unsupported context is rejected
- **WHEN** `session.context_type` does not match any supported context
- **THEN** the dispatcher returns a rejected copy of the active intent and leaves pending state unchanged

### Requirement: Dispatcher boundaries
The dispatcher SHALL reuse existing services and orchestrators; it SHALL NOT perform SQLAlchemy queries, repository access, commits, rollback, HTTP concerns, response generation, queue promotion, or intent classification.

#### Scenario: No transaction or infrastructure side effects
- **WHEN** the dispatcher completes any path
- **THEN** it has not committed, rolled back, generated responses, promoted queues, or classified a new intent

### Requirement: Public surface is limited
The dispatcher module SHALL export only `dispatch_pending_context` through `__all__` and SHALL NOT introduce a generic context abstraction.

#### Scenario: Single public dispatcher symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["dispatch_pending_context"]`
