## ADDED Requirements

### Requirement: modificar_producto delegation

When a `ProcessedIntent.intent == "modificar_producto"`, the response orchestrator SHALL call `build_modificar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

#### Scenario: modificar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "executed"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "pending_resolution"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "rejected"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "failed"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto does not invoke other response builders

- **WHEN** the orchestrator handles a `modificar_producto` item
- **THEN** `build_agregar_producto_response` and `build_quitar_producto_response` are NOT invoked

### Requirement: Unsupported intent generic response excludes modificar_producto

When a `ProcessedIntent.intent` is anything other than `"agregar_producto"`, `"quitar_producto"`, or `"modificar_producto"` (including `desconocida`, `saludo`, `consultar_pedido`, or any future intent name), the response orchestrator SHALL append a deterministic generic `CustomerResponse`. The response orchestrator SHALL NOT invoke `build_agregar_producto_response`, `build_quitar_producto_response`, `build_modificar_producto_response`, or any other response builder for that item.

#### Scenario: desconocida returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "desconocida"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")`

#### Scenario: saludo returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "saludo"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="saludo", status="rejected")`
