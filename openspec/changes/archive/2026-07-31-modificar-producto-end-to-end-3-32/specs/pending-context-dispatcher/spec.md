## ADDED Requirements

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
