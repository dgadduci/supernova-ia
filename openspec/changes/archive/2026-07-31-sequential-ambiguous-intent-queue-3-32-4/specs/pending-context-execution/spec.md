## ADDED Requirements

### Requirement: Promotion returns the next unresolved agregar_producto interaction
After an active `agregar_producto` reaches definitive `executed` or `rejected`, pending execution SHALL promote the persisted FIFO queue head. If the promoted intent is `pending_resolution`, execution SHALL append that intent exactly once after the definitive outcome, make it the active interaction, and stop.

#### Scenario: Executed active is followed by promoted clarification
- **WHEN** the active Carne addition executes and queued Pizza is `pending_resolution`
- **THEN** results are Carne `executed` then Pizza `pending_resolution`, Pizza is active, and the queue tail is preserved

#### Scenario: Rejected active still promotes clarification
- **WHEN** the active addition is definitively rejected and the queue head is unresolved
- **THEN** results are the rejection then the promoted `pending_resolution`, and the session is not left on the rejected item

### Requirement: Promotion drains ready additions until the next interaction boundary
Pending execution SHALL inspect each promoted persisted intent in FIFO order. It SHALL execute promoted `ready` additions immediately, continue after definitive `executed` or `rejected` outcomes, and stop only when the queue is exhausted, an active intent requires clarification, or a handler returns `failed`.

#### Scenario: Pending ready pending sequence advances deterministically
- **WHEN** resolving pending A promotes ready B followed by pending C
- **THEN** A executes, B executes exactly once, C becomes active, and results are A `executed`, B `executed`, C `pending_resolution`

#### Scenario: Finite ready queue is fully drained
- **WHEN** all promoted additions are ready
- **THEN** each executes exactly once in FIFO order and pending context clears after the finite queue is exhausted

#### Scenario: Failed result stops advancement
- **WHEN** a promoted ready handler returns `failed`
- **THEN** that intent remains active, the remaining queue is unchanged, and no later handler executes

### Requirement: Promoted context type comes from the promoted intent
When a promoted intent remains unresolved, pending execution SHALL determine its context type through the existing context-type resolver and persist that context for the active intent. It SHALL NOT blindly reuse a completed intent's context type.

#### Scenario: Promoted product selection restores product context
- **WHEN** an unresolved queued `agregar_producto` is promoted
- **THEN** `session.context_type` equals `product_selection` as resolved from that promoted intent

### Requirement: Promotion preserves persisted intent data
Promotion SHALL use the queued `ProcessedIntent` value without rerunning the intent classifier or rebuilding it from response text. Quantity, candidate IDs, source text, resolved data, requirements, status, handler, intent name, and refinement state SHALL remain unchanged until the active resolver legitimately refines them.

#### Scenario: Quantity and candidates survive promotion
- **WHEN** a queued Pizza intent stores quantity 2 and a restricted set of candidate IDs
- **THEN** the promoted intent still has quantity 2 and the same candidate IDs before customer refinement

### Requirement: Promotion preserves outer transaction ownership
Pending execution SHALL NOT commit or roll back. A raised handler or lower-layer exception SHALL propagate unchanged so the transactional processor can roll back all order mutations and pending-state advancement from the current incoming message.

#### Scenario: Later promoted execution raises
- **WHEN** an earlier promoted addition mutates the order in memory and a later handler raises
- **THEN** the exception propagates and pending execution performs no commit, rollback, or false-success return
