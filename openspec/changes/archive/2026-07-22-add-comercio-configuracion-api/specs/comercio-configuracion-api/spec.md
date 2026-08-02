## ADDED Requirements

### Requirement: Retrieve complete commerce configuration
The system SHALL expose `GET /comercios/{comercio_id}/configuracion` and return all scalar commerce fields plus its related status, payment-method associations with catalog records, and delivery-method associations with catalog records.

#### Scenario: Existing commerce configuration is returned
- **WHEN** the requested commerce exists
- **THEN** the endpoint returns `200 OK` with commerce scalars and all required nested configuration

#### Scenario: Missing commerce returns 404
- **WHEN** no commerce exists with the requested ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Include payment configuration
The response SHALL include every `ComercioMedioPago` belonging to the commerce, ordered by association ID, and each association SHALL include its related `MediosPago` record.

#### Scenario: Payment associations are scoped and detailed
- **WHEN** the commerce has payment-method associations
- **THEN** only its associations are returned in ID order with each catalog record included

#### Scenario: Commerce has no payment associations
- **WHEN** the commerce has no configured payment methods
- **THEN** `medios_pago` is an empty array

### Requirement: Include delivery configuration
The response SHALL include every `ComercioMetodoEntrega` belonging to the commerce, ordered by `orden` and then association ID, and each association SHALL include its related `MetodosEntrega` record.

#### Scenario: Delivery associations are scoped and ordered
- **WHEN** the commerce has delivery-method associations
- **THEN** only its associations are returned in required order with each catalog record included

#### Scenario: Commerce has no delivery associations
- **WHEN** the commerce has no configured delivery methods
- **THEN** `metodos_entrega` is an empty array

### Requirement: Exclude product-domain data
The response and repository query SHALL NOT expose or load product categories, products, presentations, prices, or product-presentation associations.

#### Scenario: Configuration response remains bounded
- **WHEN** a commerce has product-domain records
- **THEN** none of those records or relationship fields appear in the response

### Requirement: Load configuration efficiently and read-only
The repository SHALL eagerly load all required relationships without N+1 queries. The service and repository SHALL NOT commit, roll back, or modify database state, and the router SHALL contain no SQLAlchemy queries.

#### Scenario: Nested serialization uses preloaded data
- **WHEN** the response is serialized
- **THEN** required nested records are already loaded and no per-association queries are issued

#### Scenario: Read leaves database unchanged
- **WHEN** configuration is requested
- **THEN** no database write or transaction-finalization operation occurs
