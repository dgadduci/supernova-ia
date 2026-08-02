## ADDED Requirements

### Requirement: Definitive active completion preserves and promotes queued work
The pending-intent lifecycle SHALL remove only the definitive active intent and SHALL promote the FIFO queue head through `remove_active`. It SHALL clear the complete pending state only when no active or queued item remains.

#### Scenario: Executed active promotes queue head
- **WHEN** an active addition reaches `executed` while two additions remain queued
- **THEN** the former queue head becomes active and only the remaining tail stays queued

#### Scenario: Rejected active promotes queue head
- **WHEN** an active addition reaches definitive `rejected` while another addition is queued
- **THEN** the rejected active is removed and the queued addition becomes active

#### Scenario: Last definitive item empties pending state
- **WHEN** the active addition reaches a definitive result and the queue is empty
- **THEN** pending state becomes the default with no active item and an empty queue

### Requirement: Non-definitive outcomes preserve the complete queue
A `pending_resolution` or `failed` active result SHALL remain active and SHALL NOT remove, reorder, or clear queued additions.

#### Scenario: Failed active retains later additions
- **WHEN** active execution returns `failed` with two queued additions
- **THEN** the failed active and both queued additions remain persisted in their original order
