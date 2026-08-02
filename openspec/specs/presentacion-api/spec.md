# Capability: presentacion-api

## Purpose

Define the HTTP layer over the existing `Presentacion` model — a commerce-owned catalog whose rows will later participate in `ProductoPresentacion` associations — so clients can list, retrieve, and create product presentations within a commerce through the same FastAPI conventions established in earlier subphases (Router → Service → Repository → Model), while enforcing commerce-scoped uniqueness on `codigo` and `descripcion`, preserving model defaults, and isolating ownership from the request body.

## Requirements

### Requirement: List presentations owned by a commerce
The system SHALL expose `GET /comercios/{comercio_id}/presentaciones`, verify that the commerce exists, and return only presentations whose `id_comercio` matches the route parameter, ordered by `orden` ascending and then `id` ascending.

#### Scenario: Existing commerce presentations are returned in order
- **WHEN** an existing commerce owns presentations
- **THEN** the endpoint returns `200 OK` with only that commerce's presentations ordered by `orden` and then `id`

#### Scenario: Existing commerce has no presentations
- **WHEN** the commerce exists but owns no presentations
- **THEN** the endpoint returns `200 OK` with an empty JSON array

#### Scenario: Missing commerce cannot be listed
- **WHEN** no commerce exists for `comercio_id`
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve a presentation by id
The system SHALL expose `GET /presentaciones/{presentacion_id}` and return the matching presentation without loading or serializing product-presentation associations.

#### Scenario: Existing presentation is returned
- **WHEN** a presentation exists with the requested ID
- **THEN** the endpoint returns `200 OK` with its persisted scalar fields

#### Scenario: Missing presentation returns 404
- **WHEN** no presentation exists with the requested ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Create a presentation under a commerce
The system SHALL expose `POST /comercios/{comercio_id}/presentaciones`, verify the commerce exists, and create a presentation whose `id_comercio` comes exclusively from the path.

#### Scenario: Valid presentation is created
- **WHEN** an existing commerce receives valid code and description values
- **THEN** the endpoint returns `201 Created` and the presentation belongs to that commerce

#### Scenario: Missing commerce prevents creation
- **WHEN** no commerce exists for `comercio_id`
- **THEN** the endpoint returns `404 Not Found` and no presentation is inserted

#### Scenario: Request body cannot override commerce ownership
- **WHEN** the request body includes `id_comercio`
- **THEN** request validation rejects the payload before insertion

### Requirement: Validate presentations and enforce commerce-scoped uniqueness
The system SHALL trim and lowercase `codigo`, trim `descripcion`, reject empty values, reject negative supplied `orden`, forbid lifecycle and undeclared fields, preserve omitted defaults, and reject duplicate `codigo` or `descripcion` within the same commerce using case-insensitive comparison. The same values SHALL be allowed in different commerces.

#### Scenario: Code and description are normalized
- **WHEN** a valid request contains surrounding whitespace and mixed-case code
- **THEN** the persisted code is trimmed and lowercase and the description is trimmed

#### Scenario: Empty values are rejected
- **WHEN** `codigo` or `descripcion` is empty after trimming
- **THEN** the endpoint returns `400 Bad Request` and inserts no presentation

#### Scenario: Negative order is rejected
- **WHEN** the request supplies `orden` below zero
- **THEN** request validation rejects the payload and inserts no presentation

#### Scenario: Optional fields use model defaults
- **WHEN** the request omits `activo` and `orden`
- **THEN** the created presentation has `activo=true` and `orden=0`

#### Scenario: Duplicate code is scoped to one commerce
- **WHEN** a presentation in the same commerce already has the requested code ignoring case
- **THEN** the endpoint returns `409 Conflict`

#### Scenario: Duplicate description is scoped to one commerce
- **WHEN** a presentation in the same commerce already has the requested description ignoring case
- **THEN** the endpoint returns `409 Conflict`

#### Scenario: Values may repeat in another commerce
- **WHEN** another commerce uses the same code and description
- **THEN** creation succeeds with `201 Created`

### Requirement: Preserve layering and transaction ownership
The system SHALL implement presentation endpoints through `Router → Service → Repository → SQLAlchemy Model`. The router SHALL translate domain exceptions into HTTP responses, the service SHALL own commit and rollback, and the repository SHALL NOT commit, roll back, or load product associations.

#### Scenario: Domain exceptions become HTTP statuses
- **WHEN** the service raises a missing-resource, duplicate-code, or duplicate-description exception
- **THEN** the router returns `404` or `409` as appropriate

#### Scenario: Database failure is rolled back
- **WHEN** persistence fails during presentation creation
- **THEN** the service rolls back the transaction and no partial presentation remains