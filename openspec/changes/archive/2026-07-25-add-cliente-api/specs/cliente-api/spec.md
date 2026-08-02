## ADDED Requirements

### Requirement: Create cliente
The system SHALL provide `POST /clientes` that creates a new cliente. The service SHALL normalize the supplied `whatsapp` to E.164 (digits only with a leading `+`, country code intact) before persistence. The response SHALL return the persisted cliente with the canonical `whatsapp` value. The endpoint SHALL reject duplicate `whatsapp` numbers with HTTP 409.

#### Scenario: Successful creation
- **WHEN** the operator calls `POST /clientes` with `whatsapp` and optional `nombre` / `domicilio`
- **THEN** the system creates the cliente, normalizes `whatsapp` to E.164, and returns the persisted row

#### Scenario: WhatsApp normalization strips formatting
- **WHEN** the operator calls `POST /clientes` with a `whatsapp` value that contains spaces, dashes, or parentheses
- **THEN** the system stores the E.164 form (`+` followed by digits only) and returns it in the response

#### Scenario: Duplicate WhatsApp returns 409
- **WHEN** the operator calls `POST /clientes` with a `whatsapp` that already exists (after E.164 normalization)
- **THEN** the system returns 409 and persists no row

### Requirement: Retrieve cliente by id
The system SHALL provide `GET /clientes/{cliente_id}` that returns the cliente's scalar fields. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Existing cliente is returned
- **WHEN** the operator calls `GET /clientes/{cliente_id}` with an existing id
- **THEN** the system returns the cliente's scalar fields including `activo` and `created_at` / `updated_at`

#### Scenario: Missing cliente returns 404
- **WHEN** the operator calls `GET /clientes/{cliente_id}` with a non-existent id
- **THEN** the system returns 404

### Requirement: Retrieve cliente by WhatsApp
The system SHALL provide `GET /clientes/whatsapp/{whatsapp}` that returns the cliente matching the supplied WhatsApp number (after E.164 normalization). The endpoint SHALL return 404 when no cliente matches.

#### Scenario: Match returns the cliente
- **WHEN** the operator calls `GET /clientes/whatsapp/{whatsapp}` with a value that matches an existing cliente (after normalization)
- **THEN** the system returns the cliente's scalar fields

#### Scenario: No match returns 404
- **WHEN** the operator calls `GET /clientes/whatsapp/{whatsapp}` with a value that does not match any cliente
- **THEN** the system returns 404

### Requirement: Update cliente
The system SHALL provide `PUT /clientes/{cliente_id}` that updates `nombre`, `domicilio`, and optionally `activo`. The endpoint SHALL NOT accept `whatsapp`; the field is immutable through this endpoint and any supplied value SHALL be rejected by the schema (`extra="forbid"` rejects the unknown field). The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Update persists new values
- **WHEN** the operator calls `PUT /clientes/{cliente_id}` with `nombre`, `domicilio`, and/or `activo`
- **THEN** the system updates the supplied fields, leaves the others untouched, and returns the updated cliente

#### Scenario: WhatsApp field is rejected
- **WHEN** the operator calls `PUT /clientes/{cliente_id}` with a `whatsapp` field
- **THEN** the system returns 422 (Pydantic `extra="forbid"`) and the row is unchanged

#### Scenario: Update missing cliente returns 404
- **WHEN** the operator calls `PUT /clientes/{cliente_id}` with a non-existent id
- **THEN** the system returns 404 and persists no row

### Requirement: Activate and deactivate cliente
The system SHALL provide `PATCH /clientes/{cliente_id}/activo` that flips the `activo` flag to the supplied value. The endpoint SHALL accept a single boolean field. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Activate sets activo to true
- **WHEN** the cliente exists and the operator calls the endpoint with `activo=true`
- **THEN** the system sets `activo=true`, returns 200, and returns the updated cliente

#### Scenario: Deactivate sets activo to false
- **WHEN** the cliente exists and the operator calls the endpoint with `activo=false`
- **THEN** the system sets `activo=false`, returns 200, and returns the updated cliente

#### Scenario: Missing cliente returns 404
- **WHEN** the operator calls the endpoint with a non-existent id
- **THEN** the system returns 404

### Requirement: Cliente has no session relationship
The `Cliente` model SHALL NOT declare any `Session` relationship or `session_id` column during the active subphase. No endpoint SHALL accept or return session data as part of the cliente payload.

#### Scenario: Cliente payloads omit session data
- **WHEN** the operator creates, retrieves, or updates a cliente
- **THEN** no session field appears in the request body or response body

### Requirement: WhatsApp is the canonical identifier
The `clientes.whatsapp` column SHALL be unique across all rows. The service SHALL reject any write attempt that would produce a duplicate `whatsapp` value (after E.164 normalization) with HTTP 409.

#### Scenario: DB-level unique constraint prevents duplicates
- **WHEN** the service-level check is bypassed and two rows attempt the same `whatsapp`
- **THEN** the database unique index returns an integrity error and the service surfaces 409