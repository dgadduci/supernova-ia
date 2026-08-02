## ADDED Requirements

### Requirement: Retrieve a price by product-presentation
The system SHALL expose `GET /producto-presentaciones/{producto_presentacion_id}/precio`, verify that the product-presentation exists, and return its associated price without relationship details.

#### Scenario: Associated price is returned
- **WHEN** the product-presentation exists and has a price
- **THEN** the endpoint returns `200 OK` with that price

#### Scenario: Existing association has no price
- **WHEN** the product-presentation exists but no price is associated
- **THEN** the endpoint returns `404 Not Found`

#### Scenario: Missing association returns 404
- **WHEN** no product-presentation exists for the route ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve a price by id
The system SHALL expose `GET /precios/{precio_id}` and return the matching price's scalar fields without product or presentation details.

#### Scenario: Existing price is returned
- **WHEN** a price exists with the requested ID
- **THEN** the endpoint returns `200 OK`

#### Scenario: Missing price returns 404
- **WHEN** no price exists with the requested ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Create one price for a product-presentation
The system SHALL expose `POST /producto-presentaciones/{producto_presentacion_id}/precio`, verify association existence, derive ownership exclusively from the path, and create at most one price for that association.

#### Scenario: Valid price is created
- **WHEN** an existing product-presentation without a price receives a valid value
- **THEN** the endpoint returns `201 Created`

#### Scenario: Missing association prevents creation
- **WHEN** no product-presentation exists for the route ID
- **THEN** the endpoint returns `404 Not Found` and inserts no price

#### Scenario: Body cannot override association ownership
- **WHEN** the request includes `id_producto_presentacion`
- **THEN** validation rejects the request before insertion

#### Scenario: Duplicate price returns conflict
- **WHEN** the product-presentation already has a price
- **THEN** the endpoint returns `409 Conflict` and inserts no second price

### Requirement: Validate and preserve decimal price values
The system SHALL accept `Decimal`-compatible values, reject negative values, reject more than two decimal places, enforce `Numeric(12, 2)` precision, normalize accepted values to two decimal places, and preserve decimal precision without binary floating-point conversion.

#### Scenario: Two-decimal value is preserved
- **WHEN** a valid two-decimal price is created and retrieved
- **THEN** the response represents the same exact decimal value

#### Scenario: Negative price is rejected
- **WHEN** the request supplies a negative value
- **THEN** validation rejects the request

#### Scenario: Excess decimal places are rejected
- **WHEN** the request supplies more than two decimal places
- **THEN** validation rejects the request

#### Scenario: Excess precision is rejected
- **WHEN** the request exceeds 12 total digits or 10 whole-number digits
- **THEN** validation rejects the request

### Requirement: Preserve layering and transaction ownership
The system SHALL implement price endpoints through `Router → Service → Repository → SQLAlchemy Model`. The service SHALL own commit and rollback; the repository SHALL NOT finalize transactions or load relationships; the router SHALL translate domain exceptions.

#### Scenario: Domain exceptions become HTTP statuses
- **WHEN** the service raises missing-resource or duplicate-price exceptions
- **THEN** the router returns `404` or `409` as appropriate

#### Scenario: Database failure is rolled back
- **WHEN** price persistence fails
- **THEN** the service rolls back and no partial price remains
