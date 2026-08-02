## ADDED Requirements

### Requirement: List products by category
The system SHALL expose `GET /categorias-productos/{categoria_producto_id}/productos`, verify that the category exists, and return only products belonging to it, ordered by product `orden` ascending and then product `id` ascending.

#### Scenario: Category products are returned in order
- **WHEN** an existing category owns products
- **THEN** the endpoint returns `200 OK` with only those products in the required order

#### Scenario: Existing category has no products
- **WHEN** the category exists but owns no products
- **THEN** the endpoint returns `200 OK` with an empty array

#### Scenario: Missing category returns 404
- **WHEN** no category exists for the route ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: List products by commerce
The system SHALL expose `GET /comercios/{comercio_id}/productos`, verify commerce existence, and return only products belonging to categories owned by that commerce, ordered by category `orden`, product `orden`, and product `id`, all ascending.

#### Scenario: Commerce products are scoped and ordered
- **WHEN** an existing commerce has products across its categories
- **THEN** the endpoint returns only those products in the required category/product order

#### Scenario: Existing commerce has no products
- **WHEN** the commerce exists but has no products
- **THEN** the endpoint returns `200 OK` with an empty array

#### Scenario: Missing commerce returns 404
- **WHEN** no commerce exists for the route ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve a product by id
The system SHALL expose `GET /productos/{producto_id}` and return the matching product's scalar fields without category details or presentation associations.

#### Scenario: Existing product is returned
- **WHEN** a product exists with the requested ID
- **THEN** the endpoint returns `200 OK` with its persisted scalar fields

#### Scenario: Missing product returns 404
- **WHEN** no product exists with the requested ID
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Create a product under a category
The system SHALL expose `POST /categorias-productos/{categoria_producto_id}/productos`, verify category existence, and derive `id_categoria_producto` exclusively from the path.

#### Scenario: Valid product is created
- **WHEN** an existing category receives a valid product payload
- **THEN** the endpoint returns `201 Created` and the product belongs to that category

#### Scenario: Missing category prevents creation
- **WHEN** no category exists for the route ID
- **THEN** the endpoint returns `404 Not Found` and inserts no product

#### Scenario: Body cannot override category ownership
- **WHEN** the request includes `id_categoria_producto`
- **THEN** validation rejects the request before insertion

### Requirement: Validate product input and scoped uniqueness
The system SHALL trim `nombre`, reject it when empty, trim supplied `descripcion` and convert an empty result to `null`, reject negative supplied `orden`, forbid lifecycle and undeclared fields, preserve omitted defaults, and reject duplicate names within the same category using case-insensitive comparison. The same name SHALL be allowed in another category.

#### Scenario: Product text is normalized
- **WHEN** valid text contains surrounding whitespace
- **THEN** the persisted name and non-empty description are trimmed

#### Scenario: Empty description becomes null
- **WHEN** a supplied description is empty after trimming
- **THEN** the persisted description is `null`

#### Scenario: Empty name is rejected
- **WHEN** the name is empty after trimming
- **THEN** the endpoint returns `400 Bad Request`

#### Scenario: Negative order is rejected
- **WHEN** supplied `orden` is below zero
- **THEN** validation rejects the request

#### Scenario: Model defaults are preserved
- **WHEN** `activo`, `disponible`, and `orden` are omitted
- **THEN** the created product has `true`, `true`, and `0` respectively

#### Scenario: Duplicate name is category-scoped
- **WHEN** the same category already has the requested name ignoring case
- **THEN** the endpoint returns `409 Conflict`

#### Scenario: Name may repeat in another category
- **WHEN** another category uses the same name
- **THEN** creation succeeds with `201 Created`

### Requirement: Preserve layering and transaction ownership
The system SHALL implement product endpoints through `Router → Service → Repository → SQLAlchemy Model`. The service SHALL own commit and rollback; repositories SHALL NOT finalize transactions or load category/presentation relationships; routers SHALL translate domain exceptions.

#### Scenario: Domain exceptions become HTTP statuses
- **WHEN** the service raises missing-resource or duplicate-name exceptions
- **THEN** the router returns `404` or `409` as appropriate

#### Scenario: Database failure is rolled back
- **WHEN** product persistence fails
- **THEN** the service rolls back and no partial product remains
