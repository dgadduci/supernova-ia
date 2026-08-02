## ADDED Requirements

### Requirement: Discriminating fragments resolve only within persisted active candidates
The resolver SHALL evaluate a product-selection clarification only against the catalog restricted to the active intent's persisted `candidate_ids`. When `picante`, `la picante`, `carne picante`, `la común`, or `la de carne común` uniquely distinguishes one valid candidate, the resolver SHALL select that candidate without broadening recognition to the commerce catalog.

#### Scenario: Picante uniquely selects active Carne candidate
- **WHEN** the active candidates are Empanada de Carne Picante Unidad and Empanada de Carne Unidad and the message is `picante`
- **THEN** the resolver selects only Empanada de Carne Picante Unidad

#### Scenario: Selected ID must remain in active candidate domain
- **WHEN** recognition yields an ID that is not present in the active intent's original `candidate_ids`
- **THEN** the resolver returns the active intent unchanged and does not mutate the queue

### Requirement: Unique fragment resolution produces a ready intent without data loss
When a discriminating fragment leaves exactly one valid candidate, the resolver SHALL return a new intent with that `producto_presentacion_id`, mark the product requirement completed, clear `candidate_ids`, preserve existing `resolved_data` including `cantidad`, and set status to `ready` when all required requirements are complete.

#### Scenario: Quantity survives unique fragment resolution
- **WHEN** an active Carne intent has `cantidad == 4` and `picante` uniquely identifies its Picante candidate
- **THEN** the returned intent is `ready`, contains the selected ID, has empty candidate IDs, and preserves `cantidad == 4`

#### Scenario: Unique fragment does not return unchanged ambiguity
- **WHEN** one persisted active candidate uniquely matches the normalized clarification
- **THEN** the resolver does not return the unchanged `pending_resolution` intent or recreate its original candidate list

### Requirement: Partial and failed fragment refinement preserve valid pending state
When a fragment matches multiple active candidates, the resolver SHALL remain `pending_resolution` with only the valid refined candidates in original order. When it matches none, the resolver SHALL preserve the active intent unchanged. Neither path SHALL alter queued intents.

#### Scenario: Multiple matches retain refined ambiguity
- **WHEN** a fragment leaves more than one candidate from the active candidate catalog
- **THEN** the resolver returns `pending_resolution` with those candidate IDs and preserves quantity and other intent fields

#### Scenario: No match preserves active and queue
- **WHEN** a clarification matches no active candidate
- **THEN** the active intent remains unchanged and the queue is not altered
