## ADDED Requirements

### Requirement: List all delivery methods
The system SHALL expose `GET /metodos-entrega` returning all `metodos_entrega` rows ordered by `id` ascending.

#### Scenario: Existing delivery methods are returned in id order
- **WHEN** the `metodos_entrega` table contains rows
- **THEN** `GET /metodos-entrega` returns `200 OK` with a JSON array of those rows sorted by `id` ascending

### Requirement: Retrieve a delivery method by id
The system SHALL expose `GET /metodos-entrega/{metodo_entrega_id}` returning the matching row, or `404 Not Found` when no row exists for that id.

#### Scenario: Existing delivery method is returned
- **WHEN** a delivery method exists with the requested id
- **THEN** the response is `200 OK` with all persisted fields for that row

#### Scenario: Missing delivery method returns 404
- **WHEN** no delivery method exists with the requested id
- **THEN** the response is `404 Not Found`

### Requirement: Create a delivery method
The system SHALL expose `POST /metodos-entrega` accepting `codigo`, `descripcion`, `orden`, and optional `activo`, and SHALL create a new `metodos_entrega` row. The endpoint SHALL return `201 Created` on success and `409 Conflict` when `codigo` already exists.

#### Scenario: Valid payload creates a delivery method
- **WHEN** the request supplies non-empty `codigo` and `descripcion`, a non-negative `orden`, and a unique `codigo`
- **THEN** the response is `201 Created` with the persisted row and the database contains that row

#### Scenario: Duplicate codigo returns 409
- **WHEN** the request `codigo` matches an existing `metodos_entrega.codigo`
- **THEN** the response is `409 Conflict` and no row is inserted

### Requirement: Validate delivery-method creation input
The system SHALL trim surrounding whitespace from `codigo` and `descripcion`, reject either value when empty after trimming, reject negative `orden`, forbid `id`, lifecycle fields, and all other undeclared fields, and default omitted `activo` to `true`.

#### Scenario: Text fields are trimmed before persistence
- **WHEN** `codigo` or `descripcion` contains surrounding whitespace
- **THEN** the persisted values do not contain that surrounding whitespace

#### Scenario: Empty text is rejected
- **WHEN** `codigo` or `descripcion` is empty after trimming
- **THEN** the response is `400 Bad Request` and no row is inserted

#### Scenario: Negative order is rejected
- **WHEN** `orden` is less than zero
- **THEN** the request is rejected with a validation error and no row is inserted

#### Scenario: Database-managed fields are forbidden
- **WHEN** the request includes `id`, `fecha_alta`, or `fecha_ultima_modificacion`
- **THEN** the request is rejected with a validation error before any database write

### Requirement: Preserve resource layering and transaction ownership
The system SHALL implement delivery-method endpoints through `Router → Service → Repository → SQLAlchemy Model`. The router SHALL translate domain exceptions into HTTP responses, the service SHALL own commit and rollback, and the repository SHALL NOT commit or roll back transactions.

#### Scenario: Domain not-found exception becomes HTTP 404
- **WHEN** the service raises the delivery-method not-found exception
- **THEN** the router returns `404 Not Found`

#### Scenario: Database failure is rolled back
- **WHEN** persistence fails during `POST /metodos-entrega`
- **THEN** the service rolls back the transaction and no partial row remains
