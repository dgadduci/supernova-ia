## ADDED Requirements

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
