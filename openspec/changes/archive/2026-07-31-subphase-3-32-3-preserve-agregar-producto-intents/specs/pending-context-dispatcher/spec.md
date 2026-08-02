## ADDED Requirements

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
