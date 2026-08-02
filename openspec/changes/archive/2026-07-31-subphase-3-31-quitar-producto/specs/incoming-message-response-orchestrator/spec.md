## MODIFIED Requirements

### Requirement: agregar_producto delegation

When a `ProcessedIntent.intent == "agregar_producto"`, the response orchestrator SHALL call `build_agregar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

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

### Requirement: quitar_producto delegation

When a `ProcessedIntent.intent == "quitar_producto"`, the response orchestrator SHALL call `build_quitar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

#### Scenario: quitar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "executed"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "pending_resolution"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "rejected"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "failed"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

### Requirement: Unsupported intent generic response

When a `ProcessedIntent.intent` is anything other than `"agregar_producto"` or `"quitar_producto"` (including `desconocida`, `saludo`, `consultar_pedido`, or any future intent name), the response orchestrator SHALL append a deterministic generic `CustomerResponse` whose `message` is the module-level generic message, whose `intent` equals the original `ProcessedIntent.intent`, and whose `status` equals the original `ProcessedIntent.status`. The response orchestrator SHALL NOT invoke `build_agregar_producto_response`, `build_quitar_producto_response`, or any other response builder for that item.

#### Scenario: desconocida returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "desconocida"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response` and `build_quitar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")`

#### Scenario: saludo returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "saludo"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response` and `build_quitar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="saludo", status="rejected")`

#### Scenario: Generic message is deterministic and free of technical detail

- **WHEN** the orchestrator builds the generic response for any unsupported intent
- **THEN** the resulting `CustomerResponse.message` equals the module-level generic constant, does NOT contain the literal string `"id"`, `"Exception"`, `"Traceback"`, or `"Error"`, and is a single fixed Spanish string with no per-call formatting
