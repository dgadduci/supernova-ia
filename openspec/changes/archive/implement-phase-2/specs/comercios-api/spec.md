## ADDED Requirements

### Requirement: List all commerces
The system SHALL expose `GET /comercios` returning all `comercios` rows ordered by `id` ascending. The response SHALL be a JSON array of objects whose fields match the `Comercio` model's persisted columns (lifecycle fields included; `metodos_entrega` and `medios_pago` association fields excluded).

#### Scenario: Existing commerces are returned in id order
- **WHEN** at least one `comercios` row exists in the database
- **THEN** `GET /comercios` returns `200 OK` with a JSON array containing those rows sorted by `id` ascending

### Requirement: Retrieve a single commerce by id
The system SHALL expose `GET /comercios/{comercio_id}` returning the matching `comercios` row, or `404 Not Found` when no row exists for that id. The response body shape matches the `GET /comercios` row shape.

#### Scenario: Existing commerce is returned
- **WHEN** a `comercios` row exists with the given `comercio_id`
- **THEN** the response is `200 OK` and the JSON body carries that row's fields

#### Scenario: Missing commerce returns 404
- **WHEN** no `comercios` row exists with the given `comercio_id`
- **THEN** the response is `404 Not Found`

### Requirement: Create a commerce
The system SHALL expose `POST /comercios` accepting a `ComercioCreate` payload and creating a new `comercios` row. The endpoint SHALL return `201 Created` with the resulting row on success, `404 Not Found` when `estado_id` does not reference an existing `estado_comercio` row, and `409 Conflict` when the `whatsapp` or `slug` already exists in another row. The system SHALL roll back the transaction on any database error during creation.

#### Scenario: Valid payload creates the commerce
- **WHEN** the request body satisfies all validation rules and `estado_id` references an existing estado
- **THEN** the response is `201 Created` with the new row's fields populated and the database contains the new row

#### Scenario: Missing estado_id returns 404
- **WHEN** the request body's `estado_id` does not match any existing `estado_comercio` row
- **THEN** the response is `404 Not Found` and no row is inserted

#### Scenario: Duplicate whatsapp returns 409
- **WHEN** the request body's `whatsapp` matches an existing `comercios.whatsapp`
- **THEN** the response is `409 Conflict` and no row is inserted

#### Scenario: Duplicate slug returns 409
- **WHEN** the request body's `slug` matches an existing `comercios.slug`
- **THEN** the response is `409 Conflict` and no row is inserted

### Requirement: Request validation rules for commerce creation
The system SHALL apply the following validation rules on `POST /comercios` before any database call: trim surrounding whitespace from every text field, reject empty required text values, verify `estado_id` references an existing `estado_comercio` row, reject duplicate `whatsapp`, and reject duplicate `slug`. The request SHALL NOT accept lifecycle fields (`fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`, `id`).

#### Scenario: Whitespace is trimmed before persistence
- **WHEN** the request body contains text fields with surrounding whitespace
- **THEN** the persisted row stores the trimmed values

#### Scenario: Lifecycle fields are not accepted
- **WHEN** the request body includes `fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`, or `id`
- **THEN** the request is rejected with a validation error before any database call

#### Scenario: Locale fields fall back to model defaults when omitted
- **WHEN** the request body omits `zona_horaria`, `moneda`, or `idioma`
- **THEN** the persisted row uses the model's server defaults for those fields

### Requirement: Layering and HTTP error translation
The system SHALL arrange the commerce endpoints as `Router → Service → Repository → SQLAlchemy Model → PostgreSQL`. The router SHALL translate domain-specific exceptions raised by the service into HTTP status codes (`404` for not-found, `409` for duplicate whatsapp/slug, `201` for successful creation). The service SHALL raise domain-specific exceptions (not `HTTPException`) and SHALL own `commit()` and `rollback()`. The repository SHALL NOT call `commit()` or `rollback()`.

#### Scenario: Domain exception becomes HTTP status
- **WHEN** the service raises a duplicate-whatsapp exception
- **THEN** the router returns `409 Conflict` to the client

#### Scenario: Transaction is rolled back on database error
- **WHEN** the underlying insert fails (e.g., constraint violation) during `POST /comercios`
- **THEN** the service rolls the transaction back so no partial row remains
