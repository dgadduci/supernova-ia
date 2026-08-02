## ADDED Requirements

### Requirement: Create pedido
The system SHALL provide `POST /pedidos` that creates a new pedido. The new row SHALL have `estado_pedido = borrador` regardless of the request body. The fields `id_medio_pago`, `id_metodo_entrega`, and `datetime_entrega_programada` SHALL each be accepted as nullable. The response SHALL return the persisted pedido. When the request body supplies a non-null `id_medio_pago` or `id_metodo_entrega` that does not exist in the corresponding catalog, the system SHALL return HTTP 400 and persist no row.

#### Scenario: Creation defaults to borrador
- **WHEN** the operator calls `POST /pedidos` with no body fields
- **THEN** the system creates a pedido with `estado_pedido = borrador`, all nullable fields unset, and returns the persisted row

#### Scenario: Creation accepts optional fields
- **WHEN** the operator calls `POST /pedidos` with `id_medio_pago`, `id_metodo_entrega`, and/or `datetime_entrega_programada`
- **THEN** the system persists the provided fields and still creates the pedido in `borrador`

#### Scenario: Creation with unknown FK id is rejected
- **WHEN** the operator calls `POST /pedidos` with an `id_medio_pago` or `id_metodo_entrega` that does not exist
- **THEN** the system returns 400 and persists no row

### Requirement: Retrieve pedido by id
The system SHALL provide `GET /pedidos/{pedido_id}` that returns the pedido's scalar fields. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Existing pedido is returned
- **WHEN** the operator calls `GET /pedidos/{pedido_id}` with an existing id
- **THEN** the system returns the pedido's scalar fields including `estado_pedido`

#### Scenario: Missing pedido returns 404
- **WHEN** the operator calls `GET /pedidos/{pedido_id}` with a non-existent id
- **THEN** the system returns 404

### Requirement: Set payment method on borrador
The system SHALL provide `PUT /pedidos/{pedido_id}/medio-pago` that updates `id_medio_pago`. The endpoint SHALL accept the field as nullable. The endpoint SHALL reject the call when the pedido is not in `borrador` with HTTP 409. The endpoint SHALL validate that the supplied `id_medio_pago` exists in the `medios_pago` catalog when it is non-null and SHALL return HTTP 400 when it does not.

#### Scenario: Update succeeds on borrador
- **WHEN** the pedido is in `borrador` and the operator calls the endpoint with a valid `id_medio_pago`
- **THEN** the system persists the value and returns the updated pedido

#### Scenario: Update rejected outside borrador
- **WHEN** the pedido is in any state other than `borrador`
- **THEN** the system returns 409 and the row is unchanged

#### Scenario: Unknown medio_pago id is rejected
- **WHEN** the operator calls the endpoint with an `id_medio_pago` that does not exist
- **THEN** the system returns 400 and the row is unchanged

### Requirement: Set delivery method on borrador
The system SHALL provide `PUT /pedidos/{pedido_id}/metodo-entrega` that updates `id_metodo_entrega`. The endpoint SHALL accept the field as nullable. The endpoint SHALL reject the call when the pedido is not in `borrador` with HTTP 409. The endpoint SHALL validate that the supplied `id_metodo_entrega` exists in the `metodos_entrega` catalog when it is non-null and SHALL return HTTP 400 when it does not.

#### Scenario: Update succeeds on borrador
- **WHEN** the pedido is in `borrador` and the operator calls the endpoint with a valid `id_metodo_entrega`
- **THEN** the system persists the value and returns the updated pedido

#### Scenario: Update rejected outside borrador
- **WHEN** the pedido is in any state other than `borrador`
- **THEN** the system returns 409 and the row is unchanged

#### Scenario: Unknown metodo_entrega id is rejected
- **WHEN** the operator calls the endpoint with an `id_metodo_entrega` that does not exist
- **THEN** the system returns 400 and the row is unchanged

### Requirement: Set scheduled delivery time on borrador
The system SHALL provide `PUT /pedidos/{pedido_id}/fecha-entrega` that updates `datetime_entrega_programada`. The endpoint SHALL accept the field as nullable and SHALL require timezone-aware ISO-8601 input. The endpoint SHALL reject the call when the pedido is not in `borrador` with HTTP 409.

#### Scenario: Update succeeds on borrador
- **WHEN** the pedido is in `borrador` and the operator calls the endpoint with a valid timezone-aware datetime
- **THEN** the system persists the value and returns the updated pedido

#### Scenario: Update rejected outside borrador
- **WHEN** the pedido is in any state other than `borrador`
- **THEN** the system returns 409 and the row is unchanged

### Requirement: Change pedido state
The system SHALL provide `PUT /pedidos/{pedido_id}/estado` that updates `estado_pedido`. The endpoint SHALL accept only the allowed transitions; any other transition SHALL return HTTP 409. The new state SHALL be persisted before the response is returned.

#### Scenario: Allowed transition succeeds
- **WHEN** the operator requests an allowed transition (e.g. `borrador → ingresado`)
- **THEN** the system persists the new state and returns the updated pedido

#### Scenario: Forbidden transition returns 409
- **WHEN** the operator requests a transition not in the allowed graph (e.g. `borrador → terminado`)
- **THEN** the system returns 409 and the row is unchanged

#### Scenario: Cancellation is allowed from non-terminal working states
- **WHEN** the pedido is in `borrador`, `ingresado`, or `preparacion` and the operator requests `cancelado`
- **THEN** the system persists the new state

#### Scenario: Cancellation is forbidden from delivered states
- **WHEN** the pedido is in `terminado` or `entregado` and the operator requests `cancelado`
- **THEN** the system returns 409 and the row is unchanged

### Requirement: Allowed state graph
The system SHALL accept the following transitions and SHALL reject every other pair:
- `borrador → ingresado | cancelado`
- `ingresado → preparacion | cancelado`
- `preparacion → terminado | cancelado`
- `terminado → entregado`
- `entregado` and `cancelado` are terminal.

#### Scenario: Each allowed pair is accepted
- **WHEN** the operator requests any pair from the allowed graph
- **THEN** the system persists the new state

#### Scenario: Self-transitions are rejected
- **WHEN** the operator requests a transition from a state to itself
- **THEN** the system returns 409

### Requirement: Pedido has no session relationship
The pedido resource SHALL NOT expose any session reference. No endpoint SHALL accept or return a session identifier as part of the pedido payload.

#### Scenario: Pedido payloads omit session data
- **WHEN** the operator creates or retrieves a pedido
- **THEN** no session field appears in the request body or response body

### Requirement: Pedido declares catalog relationships
The `Pedido` model SHALL declare two SQLAlchemy `relationship` attributes, `medio_pago` (→ `MediosPago`) and `metodo_entrega` (→ `MetodosEntrega`), both nullable and lazy-loaded. Endpoints SHALL NOT include these objects in response bodies during the active subphase; they exist only to support future traversal without schema changes.

#### Scenario: Relationship attributes exist on the model
- **WHEN** the pedido model is loaded
- **THEN** `medio_pago` and `metodo_entrega` are present as relationship attributes