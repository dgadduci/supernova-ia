## Purpose

Route incoming messages to the right per-context pending orchestration based on `session.context_type`, advancing the active pending intent for `product_selection`, persisting results, and triggering ready execution while preserving validation and side-effect boundaries.

## Requirements

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

### Requirement: Product modification dispatch
When `session.context_type == "product_modification"`, the dispatcher SHALL call `resolve_product_modification(db, session, message, active_intent)` with the supplied message and the active intent, then persist the resulting intent through `set_active`. When the resolver returns `ready`, the dispatcher SHALL delegate to `execute_ready_pending_context` and return the executed result. When the resolver returns `pending_resolution`, the dispatcher SHALL persist the updated active intent and preserve the `product_modification` context type with the reduced `source_candidate_ids`, `destination_candidate_ids`, optional `cantidad`, and the updated `stage` (`source_selection` or `destination_selection`).

#### Scenario: Pending product_modification reply persists context
- **WHEN** a `product_modification` reply narrows the source candidate set and resolves to `pending_resolution` with `stage == "destination_selection"`
- **THEN** the dispatcher persists the updated active intent, preserves `context_type == "product_modification"`, and returns the refined `ProcessedIntent` with the reduced candidate sets and preserved `cantidad`

#### Scenario: Ready product_modification triggers execution
- **WHEN** a `product_modification` reply resolves to `ready`
- **THEN** the dispatcher persists the ready intent and delegates to `execute_ready_pending_context`, returning the executed result

#### Scenario: Product modification invalid candidate is rejected
- **WHEN** a `product_modification` reply resolves to `rejected` because the resolved source ID or destination ID is outside the current candidate set
- **THEN** the dispatcher returns the rejected copy and preserves the `product_modification` context type so `execute_ready_pending_context` can clear it on the way out

#### Scenario: Product modification preserves source and destination domains
- **WHEN** the resolver returns a `pending_resolution` with reduced `source_candidate_ids` and `destination_candidate_ids`
- **THEN** the dispatcher persists both lists and the `stage` field as distinct fields on the active intent; the two identifier domains are never combined into a single `candidate_ids` list

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

### Requirement: Pending dispatch returns every ordered advancement outcome
`dispatch_pending_context` SHALL return `list[ProcessedIntent]`. Product-selection dispatch SHALL update only the active intent from the customer's clarification and, when it becomes ready, SHALL return the complete ordered list produced by pending-context execution.

#### Scenario: Clarification executes active and queued ready additions
- **WHEN** a clarification makes the active addition ready and one or more queued additions are already ready
- **THEN** dispatch returns all execution outcomes in FIFO order

#### Scenario: Ambiguous clarification returns one item and preserves queue
- **WHEN** product selection remains ambiguous
- **THEN** dispatch returns a one-item list containing the updated `pending_resolution` active intent and leaves queued additions unchanged

#### Scenario: Missing or unsupported context returns one rejected item
- **WHEN** pending dispatch follows an existing rejected fallback path
- **THEN** it returns a one-item list containing that rejected `ProcessedIntent`

### Requirement: Clarification applies only to the active pending intent
When a session has an active pending intent and queued additions, the dispatcher SHALL apply a clarification-only message exclusively to the active intent. It SHALL NOT resolve, reclassify, or mutate inactive queued intents.

#### Scenario: First clarification does not resolve queued product
- **WHEN** Carne is active, Pizza is queued, and the customer replies `picante`
- **THEN** only Carne is resolved by that text and Pizza retains its persisted candidate and quantity state

### Requirement: Pending dispatch returns definitive outcome then next clarification
When active resolution becomes ready and execution promotes another unresolved addition, the dispatcher SHALL return the complete ordered execution result unchanged: the active definitive outcome first, followed by exactly one `pending_resolution` result for the newly active queue head.

#### Scenario: Carne execution precedes Pizza clarification
- **WHEN** `picante` resolves active Carne and promotes unresolved Pizza
- **THEN** dispatch returns Carne `executed` followed by Pizza `pending_resolution`

#### Scenario: No inactive queued clarification is returned
- **WHEN** more unresolved additions remain behind the promoted active item
- **THEN** dispatch returns no clarification for those inactive queue entries

### Requirement: Repeated ambiguity preserves queue order
If clarification leaves the active intent in `pending_resolution`, the dispatcher SHALL persist only the refined active intent, return one active outcome, and preserve every queued item in the same order.

#### Scenario: Ambiguous active refinement does not advance
- **WHEN** a clarification still matches multiple active candidates
- **THEN** no handler runs, one `pending_resolution` result is returned, and the queue is unchanged

### Requirement: Pending dispatch does not duplicate advancement outcomes
Each definitive or promoted unresolved intent produced during one dispatch SHALL appear exactly once and in actual processing order.

#### Scenario: Ready item between two ambiguous items appears once
- **WHEN** resolving pending A causes ready B to execute and pending C to become active
- **THEN** dispatch returns exactly A `executed`, B `executed`, and C `pending_resolution` in that order

### Requirement: Resolved active state remains authoritative through dispatch

For product selection, the dispatcher SHALL treat the resolver's returned intent as the authoritative active value for the current transaction. It SHALL persist or stage that value exactly once and SHALL NOT subsequently overwrite it with the pre-resolution active intent or an outdated serialized pending state.

#### Scenario: Ready Carne is not replaced by stale ambiguity

- **WHEN** `picante` changes active Carne from `pending_resolution` to `ready`
- **THEN** dispatch retains the ready Carne value, does not restore the old Carne candidate list, and delegates to ready pending execution

#### Scenario: Pending refinement persists only the refined active

- **WHEN** a reply legitimately leaves multiple active candidates
- **THEN** dispatch persists the refined active once and preserves every queue entry unchanged and in order

### Requirement: Unique active resolution advances without repeated clarification

When product-selection resolution returns `ready`, dispatch SHALL return the complete ordered list from pending-context execution. It SHALL NOT return the previous active clarification, enqueue a duplicate active intent, or classify the clarification message as a new initial intent.

#### Scenario: Picante does not repeat Carne clarification

- **WHEN** Carne is active, Pizza is queued, and `picante` uniquely resolves Carne
- **THEN** dispatch returns Carne's definitive execution outcome followed by the promoted Pizza clarification and does not return the Carne clarification again

#### Scenario: Clarification affects only active intent

- **WHEN** a clarification resolves active Carne while Pizza is queued
- **THEN** Pizza retains its original source text, quantity, requirements, candidate IDs, recognizer, handler, and queue position until promotion