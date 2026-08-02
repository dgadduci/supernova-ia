## ADDED Requirements

### Requirement: List all medios_pago records
The system SHALL expose `GET /medios-pago` returning all `medios_pago` rows ordered by `id` ascending.

#### Scenario: Existing rows are returned in id order
- **WHEN** the `medios_pago` table contains rows
- **THEN** `GET /medios-pago` returns `200 OK` with a JSON array of those rows sorted by `id` ascending

### Requirement: Retrieve a single medios_pago by id
The system SHALL expose `GET /medios-pago/{medio_pago_id}` returning the matching `medios_pago` row, or `404 Not Found` when no row exists for that id.

#### Scenario: Existing row is returned
- **WHEN** a `medios_pago` row exists with the given id
- **THEN** the response is `200 OK` with that row's fields

#### Scenario: Missing id returns 404
- **WHEN** no `medios_pago` row exists with the given id
- **THEN** the response is `404 Not Found`

### Requirement: Create a medios_pago
The system SHALL expose `POST /medios-pago` accepting a payload with `codigo` and `descripcion` and creating a new `medios_pago` row. The endpoint SHALL return `201 Created` on success and `409 Conflict` when the `codigo` value already exists in another row. The system SHALL roll back the transaction on any database error during creation.

#### Scenario: Valid payload creates the row
- **WHEN** the request body supplies a non-empty `codigo` and non-empty `descripcion`, and the `codigo` does not yet exist in the table
- **THEN** the response is `201 Created` with the new row's fields populated and the database contains the new row

#### Scenario: Duplicate codigo returns 409
- **WHEN** the request body's `codigo` value matches an existing `medios_pago.codigo`
- **THEN** the response is `409 Conflict` and no row is inserted

### Requirement: Request validation rules for medios_pago creation
The system SHALL apply the following validation rules on `POST /medios-pago` before any database call: trim surrounding whitespace from `codigo` and `descripcion`; reject empty `codigo` or `descripcion`. The request SHALL NOT accept `id` (the id is autoincrement and database-assigned) or any other undeclared field. The request MAY accept an optional `activo` Boolean (default `true`).

#### Scenario: Whitespace is trimmed before persistence
- **WHEN** the request body supplies `codigo` or `descripcion` with surrounding whitespace
- **THEN** the persisted row stores the trimmed values

#### Scenario: Lifecycle fields are not accepted
- **WHEN** the request body includes `id`
- **THEN** the request is rejected with a validation error before any database call

### Requirement: Layering and HTTP error translation
The system SHALL arrange the medios_pago endpoints as `Router → Service → Repository → SQLAlchemy Model → PostgreSQL`. The router SHALL translate domain-specific exceptions raised by the service into HTTP status codes (`404` for not-found, `409` for duplicate `codigo`, `201` for successful creation). The service SHALL raise domain-specific exceptions (not `HTTPException`) and SHALL own `commit()` and `rollback()`. The repository SHALL NOT call `commit()` or `rollback()`.

#### Scenario: Domain exception becomes HTTP status
- **WHEN** the service raises a duplicate-`codigo` exception
- **THEN** the router returns `409 Conflict` to the client

#### Scenario: Transaction is rolled back on database error
- **WHEN** the underlying insert fails during `POST /medios-pago`
- **THEN** the service rolls the transaction back so no partial row remains
