## MODIFIED Requirements

### Requirement: Intent order preservation

The response orchestrator SHALL preserve the order of response groups from the
inner transactional processor. It SHALL return one `CustomerResponse` for each
input `ProcessedIntent` except a consecutive group whose items all have intent
`"agregar_producto"`, status `"executed"`, and the same positive integer
`resolved_data["producto_presentacion_id"]`; that group SHALL yield exactly one
response built from its terminal item. Pending, rejected, failed, distinct, or
non-consecutive items SHALL remain individually represented.

#### Scenario: Multi-intent list preserves classifier order

- **WHEN** `process_incoming_message_transactional` returns a list of three `ProcessedIntent` items in the order `[pending_resolution, executed, rejected]`
- **THEN** `process_incoming_message_with_responses` returns a list of three `CustomerResponse` items in that same order, with the i-th `CustomerResponse` produced from the i-th `ProcessedIntent`

#### Scenario: Single-intent list has length 1

- **WHEN** `process_incoming_message_transactional` returns a one-item list
- **THEN** `process_incoming_message_with_responses` returns a one-item list

#### Scenario: Consecutive equivalent executed additions yield one terminal response

- **WHEN** the processor returns two consecutive executed `agregar_producto` items with the same positive `producto_presentacion_id`
- **THEN** the orchestrator returns one response for that group, rendered from the second item and therefore reporting its final quantity

#### Scenario: Different or interrupted additions are not coalesced

- **WHEN** two `agregar_producto` items have different presentation IDs or are separated by any other item
- **THEN** each item keeps its existing individual response in original order

### Requirement: agregar_producto delegation

For an individual `ProcessedIntent.intent == "agregar_producto"`, the response
orchestrator SHALL call `build_agregar_producto_response(db, session, intent)`
exactly once and append its returned `CustomerResponse`. For an eligible
consecutive equivalent executed-addition group, it SHALL call that builder
exactly once for the terminal item and SHALL NOT render any earlier group item.

#### Scenario: agregar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "executed"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "pending_resolution"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "failed"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: Eligible group delegates only its terminal item

- **WHEN** two consecutive executed `agregar_producto` items have the same positive `producto_presentacion_id`
- **THEN** `build_agregar_producto_response` is called once with the second item and no response is built from the first item
