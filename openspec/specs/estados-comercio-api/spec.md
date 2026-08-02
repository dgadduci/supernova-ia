# Capability: estados-comercio-api

## Purpose

Define the HTTP layer over the existing `EstadoComercio` model, so future subphases that surface `estado` references on other resources (e.g., `Comercio`) can rely on a catalog reachable through the same FastAPI conventions established in Subphase 2.1.

## Requirements

### Requirement: List all estado_comercio records
The system SHALL expose `GET /estados-comercio` returning all `estado_comercio` rows ordered by `id` ascending.

#### Scenario: Existing rows are returned in id order
- **WHEN** the `estado_comercio` table contains rows
- **THEN** `GET /estados-comercio` returns `200 OK` with a JSON array of those rows sorted by `id` ascending

### Requirement: Retrieve a single estado_comercio by id
The system SHALL expose `GET /estados-comercio/{estado_comercio_id}` returning the matching `estado_comercio` row, or `404 Not Found` when no row exists for that id.

#### Scenario: Existing row is returned
- **WHEN** an `estado_comercio` row exists with the given id
- **THEN** the response is `200 OK` with that row's fields

#### Scenario: Missing id returns 404
- **WHEN** no `estado_comercio` row exists with the given id
- **THEN** the response is `404 Not Found`

### Requirement: Create an estado_comercio
The system SHALL expose `POST /estados-comercio` accepting a payload with `estado` and creating a new `estado_comercio` row. The endpoint SHALL return `201 Created` on success and `409 Conflict` when the `estado` value already exists in another row. The system SHALL roll back the transaction on any database error during creation.

#### Scenario: Valid payload creates the row
- **WHEN** the request body supplies a non-empty `estado` value that does not yet exist in the table
- **THEN** the response is `201 Created` with the new row's fields populated and the database contains the new row

#### Scenario: Duplicate estado returns 409
- **WHEN** the request body's `estado` value matches an existing `estado_comercio.estado`
- **THEN** the response is `409 Conflict` and no row is inserted

### Requirement: Request validation rules for estado_comercio creation
The system SHALL apply the following validation rules on `POST /estados-comercio` before any database call: trim surrounding whitespace from `estado` and reject an empty `estado`. The request SHALL NOT accept `id` (the id is autoincrement and database-assigned).

#### Scenario: Whitespace is trimmed before persistence
- **WHEN** the request body supplies an `estado` value with surrounding whitespace
- **THEN** the persisted row stores the trimmed value

#### Scenario: Lifecycle fields are not accepted
- **WHEN** the request body includes `id`
- **THEN** the request is rejected with a validation error before any database call

### Requirement: Layering and HTTP error translation
The system SHALL arrange the estado_comercio endpoints as `Router → Service → Repository → SQLAlchemy Model → PostgreSQL`. The router SHALL translate domain-specific exceptions raised by the service into HTTP status codes (`404` for not-found, `409` for duplicate `estado`, `201` for successful creation). The service SHALL raise domain-specific exceptions (not `HTTPException`) and SHALL own `commit()` and `rollback()`. The repository SHALL NOT call `commit()` or `rollback()`.

#### Scenario: Domain exception becomes HTTP status
- **WHEN** the service raises a duplicate-estado exception
- **THEN** the router returns `409 Conflict` to the client

#### Scenario: Transaction is rolled back on database error
- **WHEN** the underlying insert fails during `POST /estados-comercio`
- **THEN** the service rolls the transaction back so no partial row remains
