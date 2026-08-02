# Capability: session-api

## Purpose

Define the HTTP API for creating, retrieving, updating, associating, and closing customer sessions.

## Requirements

### Requirement: Create session
The system SHALL provide `POST /sessions` that creates a new session. The new row SHALL have `estado_session = activa` and `datetime_inicio` set to the current time. `id_comercio` and `id_cliente` are required; `id_pedido` is optional. The endpoint SHALL reject a second `activa` session for the same `(id_comercio, id_cliente)` pair with HTTP 409.

#### Scenario: Successful creation
- **WHEN** the operator calls `POST /sessions` with `id_comercio` and `id_cliente`
- **THEN** the system creates a session in `activa` state, sets `datetime_inicio` to the current time, and returns the persisted row

#### Scenario: Creation without pedido
- **WHEN** the operator creates a session and omits `id_pedido`
- **THEN** the session is created with `id_pedido = null`

#### Scenario: Second active session for same pair returns 409
- **WHEN** an active session already exists for the supplied `(id_comercio, id_cliente)` pair
- **THEN** the system returns 409 and persists no row

### Requirement: Retrieve session by id
The system SHALL provide `GET /sessions/{session_id}` that returns the session's scalar fields. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Existing session is returned
- **WHEN** the operator calls `GET /sessions/{session_id}` with an existing id
- **THEN** the system returns the session's scalar fields including `estado_session`, `datetime_inicio`, and `datetime_ultimo_movimiento`

#### Scenario: Missing session returns 404
- **WHEN** the operator calls `GET /sessions/{session_id}` with a non-existent id
- **THEN** the system returns 404

### Requirement: Retrieve active session by comercio and cliente
The system SHALL provide `GET /comercios/{comercio_id}/clientes/{cliente_id}/sessions/activa` that returns the active session for the given pair, or 404 when none exists.

#### Scenario: Active session is returned
- **WHEN** an active session exists for the given `(comercio, cliente)` pair
- **THEN** the system returns the session's scalar fields

#### Scenario: No active session returns 404
- **WHEN** no active session exists for the given `(comercio, cliente)` pair
- **THEN** the system returns 404

### Requirement: Update last movement timestamp
The system SHALL provide `PATCH /sessions/{session_id}/movimiento` that updates `datetime_ultimo_movimiento` to the current time. The endpoint SHALL reject the call when the session is not `activa` with HTTP 409. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Update succeeds on active session
- **WHEN** the session is in `activa` and the operator calls the endpoint
- **THEN** the system sets `datetime_ultimo_movimiento` to the current time and returns the updated session

#### Scenario: Update rejected on closed session
- **WHEN** the session is in `cerrada` and the operator calls the endpoint
- **THEN** the system returns 409 and the timestamp is unchanged

#### Scenario: Update missing session returns 404
- **WHEN** the operator calls the endpoint with a non-existent id
- **THEN** the system returns 404

### Requirement: Associate pedido with session
The system SHALL provide `PUT /sessions/{session_id}/pedido` that associates a pedido with the session by setting `sessions.id_pedido` and `pedidos.id_session` consistently. The endpoint SHALL reject the call when the session is not `activa` with HTTP 409. The endpoint SHALL reject the call when the pedido does not exist, when the pedido is already linked to another session, or when the pedido's comercio/cliente does not match the session's comercio/cliente. The endpoint SHALL also update `datetime_ultimo_movimiento` on success.

#### Scenario: Successful association
- **WHEN** the session is `activa`, the pedido exists, and the pedido is in `borrador` with the same comercio and cliente as the session
- **THEN** the system sets `sessions.id_pedido` and `pedidos.id_session` consistently, updates `datetime_ultimo_movimiento`, and returns the updated session

#### Scenario: Pedido from another session returns 400
- **WHEN** the supplied pedido is already linked to a different session
- **THEN** the system returns 400 and no associations change

#### Scenario: Pedido with mismatched comercio or cliente returns 400
- **WHEN** the supplied pedido's comercio or cliente does not match the session's comercio or cliente
- **THEN** the system returns 400 and no associations change

#### Scenario: Pedido missing returns 404
- **WHEN** the supplied pedido id does not exist
- **THEN** the system returns 404 and no associations change

#### Scenario: Association on closed session returns 409
- **WHEN** the session is in `cerrada` and the operator calls the endpoint
- **THEN** the system returns 409 and no associations change

### Requirement: Close session
The system SHALL provide `POST /sessions/{session_id}/cerrar` that transitions the session from `activa` to `cerrada`. The endpoint SHALL reject the call when the session is already `cerrada` with HTTP 409. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Close active session
- **WHEN** the session is in `activa` and the operator calls the endpoint
- **THEN** the system sets `estado_session = cerrada`, updates `datetime_ultimo_movimiento`, and returns the updated session

#### Scenario: Close already-closed session returns 409
- **WHEN** the session is in `cerrada` and the operator calls the endpoint
- **THEN** the system returns 409 and the session is unchanged

#### Scenario: Close missing session returns 404
- **WHEN** the operator calls the endpoint with a non-existent id
- **THEN** the system returns 404
