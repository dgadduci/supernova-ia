# Capability: categoria-producto-api

## Purpose

Define the HTTP layer over the existing `CategoriaProducto` model — the first commerce-owned child resource exposed through nested commerce routes — so clients can list, retrieve, and create product categories within a commerce through the same FastAPI conventions established in earlier subphases (Router → Service → Repository → Model), while preserving model defaults, ownership boundaries, and ordered listing.

## Requirements

### Requirement: List categories owned by a commerce
The system SHALL expose `GET /comercios/{comercio_id}/categorias-productos`, verify that the commerce exists, and return only categories whose `id_comercio` matches the route parameter, ordered by `orden` ascending and then `id` ascending.

#### Scenario: Existing commerce categories are returned in order
- **WHEN** an existing commerce owns product categories
- **THEN** the endpoint returns `200 OK` with only that commerce's categories ordered by `orden` and then `id`

#### Scenario: Existing commerce has no categories
- **WHEN** the commerce exists but owns no product categories
- **THEN** the endpoint returns `200 OK` with an empty JSON array

#### Scenario: Missing commerce cannot be listed
- **WHEN** no commerce exists for `comercio_id`
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve a product category by id
The system SHALL expose `GET /categorias-productos/{categoria_producto_id}` and return the matching category without loading or serializing related products.

#### Scenario: Existing category is returned
- **WHEN** a product category exists with the requested ID
- **THEN** the endpoint returns `200 OK` with its persisted scalar fields

#### Scenario: Missing category returns 404
- **WHEN** no product category exists with the requested ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Create a category under a commerce
The system SHALL expose `POST /comercios/{comercio_id}/categorias-productos`, verify that the commerce exists, and create a category whose `id_comercio` comes exclusively from the path parameter.

#### Scenario: Valid category is created
- **WHEN** an existing commerce receives a valid category payload
- **THEN** the endpoint returns `201 Created` and the persisted category belongs to that commerce

#### Scenario: Missing commerce prevents creation
- **WHEN** no commerce exists for `comercio_id`
- **THEN** the endpoint returns `404 Not Found` and no category is inserted

#### Scenario: Request body cannot override commerce ownership
- **WHEN** the request body includes `id_comercio`
- **THEN** request validation rejects the payload before any category is inserted

### Requirement: Validate category creation input and preserve defaults
The system SHALL require `descripcion`, trim its surrounding whitespace, reject it when empty after trimming, enforce its model maximum length, reject a supplied negative `orden`, forbid lifecycle and undeclared fields, and preserve model defaults when `activo` or `orden` are omitted.

#### Scenario: Description is trimmed
- **WHEN** a valid description contains surrounding whitespace
- **THEN** the persisted description excludes that whitespace

#### Scenario: Empty description is rejected
- **WHEN** the description is empty after trimming
- **THEN** the endpoint returns `400 Bad Request` and inserts no category

#### Scenario: Negative order is rejected
- **WHEN** the request supplies `orden` below zero
- **THEN** request validation rejects the payload and inserts no category

#### Scenario: Optional fields use model defaults
- **WHEN** the request omits `activo` and `orden`
- **THEN** the created category has `activo=true` and `orden=0`

#### Scenario: Explicit optional values are preserved
- **WHEN** the request supplies valid `activo` or `orden` values
- **THEN** the created category stores those supplied values

### Requirement: Preserve layering and transaction ownership
The system SHALL implement category endpoints through `Router → Service → Repository → SQLAlchemy Model`. The router SHALL translate domain exceptions into HTTP responses, the service SHALL own commit and rollback, and the repository SHALL NOT commit or roll back transactions.

#### Scenario: Missing-resource domain exception becomes HTTP 404
- **WHEN** the service raises a commerce-not-found or category-not-found exception
- **THEN** the router returns `404 Not Found`

#### Scenario: Database failure is rolled back
- **WHEN** persistence fails during category creation
- **THEN** the service rolls back the transaction and no partial category remains
