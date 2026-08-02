## ADDED Requirements

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
