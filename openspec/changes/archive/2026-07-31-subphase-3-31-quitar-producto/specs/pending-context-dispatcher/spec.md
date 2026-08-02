## MODIFIED Requirements

### Requirement: Product selection dispatch
When `session.context_type == "product_selection"`, the dispatcher SHALL call the existing product-selection orchestration service with the supplied message and the active intent, then persist the resulting intent through `set_active`.

#### Scenario: Pending product selection reply persists context
- **WHEN** a `product_selection` reply still resolves to `pending_resolution`
- **THEN** the dispatcher persists the updated active intent and preserves context type

#### Scenario: Ready product selection triggers execution
- **WHEN** a `product_selection` reply resolves to `ready`
- **THEN** the dispatcher persists the ready intent and delegates to `execute_ready_pending_context`, returning the executed result

### Requirement: Order line selection dispatch
When `session.context_type == "order_line_selection"`, the dispatcher SHALL call `resolve_order_line_selection(db, session, message, active_intent)` with the supplied message and the active intent, then persist the resulting intent through `set_active`. When the resolver returns `ready`, the dispatcher SHALL delegate to `execute_ready_pending_context` and return the executed result. When the resolver returns `pending_resolution`, the dispatcher SHALL persist the updated active intent and preserve the `order_line_selection` context type.

#### Scenario: Order line selection refinement persists context
- **WHEN** an `order_line_selection` reply narrows the candidate set and resolves to `pending_resolution`
- **THEN** the dispatcher persists the updated active intent and preserves `context_type == "order_line_selection"`

#### Scenario: Order line selection ready triggers execution
- **WHEN** an `order_line_selection` reply resolves to `ready`
- **THEN** the dispatcher persists the ready intent and delegates to `execute_ready_pending_context`, returning the executed result

#### Scenario: Order line selection invalid candidate is rejected
- **WHEN** an `order_line_selection` reply resolves to `rejected`
- **THEN** the dispatcher returns the rejected copy and preserves the `order_line_selection` context type so `execute_ready_pending_context` can clear it on the way out

### Requirement: Unsupported or invalid context handling
The dispatcher SHALL reject unsupported or invalid context values by copying the active intent with `status == "rejected"` and SHALL NOT clear or modify pending context.

#### Scenario: Unsupported context is rejected
- **WHEN** `session.context_type` does not match any supported context
- **THEN** the dispatcher returns a rejected copy of the active intent and leaves pending state unchanged
