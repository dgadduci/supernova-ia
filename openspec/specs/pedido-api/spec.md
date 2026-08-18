# Capability: pedido-api

## Purpose

Define the HTTP layer over the `Pedido` model, covering creation, retrieval, in-progress field updates on a borrador pedido, and explicit state transitions, so the order lifecycle can be driven through the same FastAPI conventions established in earlier API subphases.
## Requirements
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

### Requirement: Pedido requires a session
The `POST /pedidos` endpoint SHALL require a non-null `id_session` field in the request body. The pedido service SHALL validate that the supplied `id_session` exists and that its `estado_session` is `activa`; otherwise the pedido creation fails with HTTP 400 (`SessionNotFound` → 404, `SessionNotActive` → 409). The persisted `pedido` row SHALL have `id_session` set to the supplied value and `estado_pedido` SHALL default to `borrador` regardless.

#### Scenario: Pedido create with valid id_session succeeds
- **WHEN** the operator calls `POST /pedidos` with a valid `id_session` of an `activa` session
- **THEN** the system creates the pedido in `borrador` with the supplied `id_session`

#### Scenario: Pedido create rejects missing id_session
- **WHEN** the operator calls `POST /pedidos` without `id_session`
- **THEN** the system returns 422 and persists no row

#### Scenario: Pedido create rejects non-existent id_session
- **WHEN** the operator calls `POST /pedidos` with an `id_session` that does not exist
- **THEN** the system returns 404 and persists no row

#### Scenario: Pedido create rejects non-active id_session
- **WHEN** the operator calls `POST /pedidos` with an `id_session` of a `cerrada` session
- **THEN** the system returns 409 and persists no row

### Requirement: Pedido declares catalog relationships
The `Pedido` model SHALL declare two SQLAlchemy `relationship` attributes, `medio_pago` (→ `MediosPago`) and `metodo_entrega` (→ `MetodosEntrega`), both nullable and lazy-loaded. Endpoints SHALL NOT include these objects in response bodies during the active subphase; they exist only to support future traversal without schema changes.

#### Scenario: Relationship attributes exist on the model
- **WHEN** the pedido model is loaded
- **THEN** `medio_pago` and `metodo_entrega` are present as relationship attributes

### Requirement: Retrieve pedido detail with human-readable line items
The system SHALL provide `GET /pedidos/{pedido_id}/detalle` that returns the pedido's scalar fields together with a `lineas` array describing its current line items. Each entry in `lineas` SHALL carry exactly three fields: `cantidad` (non-negative integer), `producto_nombre` (str), and `presentacion_descripcion` (str). The response SHALL NOT include any database identifier (`id`, `id_pedido`, `id_pedido_producto`, `id_producto_presentacion`, `id_producto`, `id_presentacion`, `id_comercio`, etc.), `precio_unitario`, `observaciones`, or any other field not listed here. The endpoint SHALL be read-only: it SHALL NOT call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; it SHALL NOT mutate the pedido or its line items. The endpoint SHALL return 404 when the `pedido_id` does not exist. The endpoint SHALL return 200 with an empty `lineas` array when the pedido exists but has no line items. Line items SHALL be returned in the order persisted by the database (ascending by `pedido_producto.id`). The `presentacion_descripcion` SHALL be the `descripcion` field of the joined `Presentacion` row; if the joined row is missing or its `descripcion` is empty, the response SHALL carry the literal string `—` (em dash, U+2014) instead.

#### Scenario: Existing pedido with line items returns scalars and ordered lineas
- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for a pedido that has at least one line item
- **THEN** the system returns 200 with the pedido's scalar fields (`id`, `id_session`, `id_medio_pago`, `id_metodo_entrega`, `datetime_entrega_programada`, `estado_pedido`, `fecha_alta`, `fecha_ultima_modificacion`) and a `lineas` array, in the persisted order, where each entry exposes only `cantidad`, `producto_nombre`, and `presentacion_descripcion`

#### Scenario: Missing pedido returns 404
- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` with a non-existent id
- **THEN** the system returns 404 and performs no mutation

#### Scenario: Empty pedido returns empty lineas
- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for a pedido that has no line items
- **THEN** the system returns 200 with the pedido's scalar fields and `lineas: []`

#### Scenario: Missing presentation description falls back to em dash
- **WHEN** a line item's joined `Presentacion.descripcion` is missing or empty
- **THEN** that entry's `presentacion_descripcion` is the literal string `—`

#### Scenario: Endpoint does not expose database identifiers
- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for any pedido
- **THEN** the response body contains no key that starts with `id_` (other than the pedido's top-level scalar identifiers carried over from `PedidoResponse`), no `precio_unitario`, and no `observaciones`

#### Scenario: Endpoint is read-only
- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle`
- **THEN** the system does not call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; the pedido and its line items are unchanged in the database

### Requirement: Confirmed orders reserve trial quota atomically

Every transition of a comercio's pedido from `BORRADOR` to `INGRESADO` SHALL
re-evaluate availability. For a PRUEBA commerce it SHALL lock and reserve one
quota unit in the same caller-owned transaction as the state transition. The
reservation SHALL not commit independently.

#### Scenario: Final trial quota admits only one concurrent confirmation

- **WHEN** two confirmations race while exactly one trial quota unit remains
- **THEN** exactly one pedido becomes INGRESADO and increments consumption
- **AND** the other remains non-confirmed with a typed unavailable outcome

#### Scenario: Failed confirmation does not consume quota

- **WHEN** a technical failure rolls back a confirmation after a trial
  reservation was staged
- **THEN** neither the pedido transition nor the counter increment persists
