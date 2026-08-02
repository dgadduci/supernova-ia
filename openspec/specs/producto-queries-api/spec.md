# Capability: producto-queries-api

## Purpose

Define the read-only HTTP API and application-layer behavior for aggregating product, category, presentation, and price data, including commerce-scoped catalog browsing, search, availability/sellable filtering, exact-name lookup, and admin detection of incomplete products, while preserving the read-only layering and reusing the existing product modules.

## Requirements

### Requirement: Retrieve complete product detail
The system SHALL expose `GET /productos/{producto_id}/detalle`, return product scalars, related category, commerce identity, every `ProductoPresentacion` ordered by association `orden` then `id`, each related `Presentacion`, and the current `Precio` when present.

#### Scenario: Existing product detail is returned
- **WHEN** the product exists
- **THEN** the endpoint returns `200 OK` with the product, category, commerce id, ordered presentations, related presentation records, and current prices when available

#### Scenario: Missing product returns 404
- **WHEN** no product exists for the route id
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve commerce product catalog
The system SHALL expose `GET /comercios/{comercio_id}/catalogo` and return categories, products, product-presentation associations, related presentations, and current prices, scoped to the commerce.

#### Scenario: Commerce catalog is scoped and ordered
- **WHEN** the commerce exists
- **THEN** the endpoint returns the commerce's category tree with stable ordering and only its products

#### Scenario: Active and available filters apply
- **WHEN** `solo_activos=true` and `solo_disponibles=true` are passed
- **THEN** the endpoint returns only active categories, active products, active presentations, and available products

#### Scenario: Missing commerce returns 404
- **WHEN** no commerce exists for the route id
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Retrieve product presentations and current prices
The system SHALL expose `GET /productos/{producto_id}/presentaciones`, `GET /productos/{producto_id}/presentaciones/{presentacion_id}`, and `GET /productos/{producto_id}/presentaciones/{presentacion_id}/precio`; each shall return 404 when required parent records are missing, and the association detail shall require the product/presentation to be linked.

#### Scenario: Product presentations list is ordered
- **WHEN** the product exists and has associations
- **THEN** the listing returns associations ordered by `orden` then `id` with related presentation and current price

#### Scenario: Specific association returns details
- **WHEN** a matching product-presentation association exists
- **THEN** the endpoint returns its scalar fields, presentation, and current price

#### Scenario: Unrelated product or presentation returns 404
- **WHEN** the product and presentation are not linked
- **THEN** the endpoint returns `404 Not Found`

#### Scenario: Association price returns current price
- **WHEN** the association has a current price
- **THEN** the endpoint returns that price with preserved decimal precision

### Requirement: Retrieve product price summary
The system SHALL expose `GET /productos/{producto_id}/precios` and return each priced product-presentation with its current price, ordered by association `orden` then `id`.

#### Scenario: Price summary preserves decimals
- **WHEN** the product has priced presentations
- **THEN** the endpoint returns one entry per priced association with exact decimal precision

### Requirement: Search and name lookups scoped to one commerce
The system SHALL expose `GET /comercios/{comercio_id}/productos/buscar` and `GET /comercios/{comercio_id}/productos/por-nombre`, validate that the commerce exists, and limit results to products owned by that commerce.

#### Scenario: Free-text search is commerce-scoped
- **WHEN** a query is supplied for an existing commerce
- **THEN** the endpoint returns matches only within that commerce

#### Scenario: Empty query is rejected
- **WHEN** the search text is empty
- **THEN** the endpoint returns `400 Bad Request`

#### Scenario: Exact-name lookup returns all category matches
- **WHEN** the same product name appears in multiple categories of one commerce
- **THEN** the endpoint returns every matching product with category, presentations, and current prices

#### Scenario: Missing name returns 404
- **WHEN** no product in the commerce matches the exact normalized name
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Available, sellable, and incomplete product detection
The system SHALL expose `GET /comercios/{comercio_id}/productos/disponibles`, `GET /comercios/{comercio_id}/productos/vendibles`, and `GET /comercios/{comercio_id}/productos/incompletos`.

#### Scenario: Available products respect availability flags
- **WHEN** the commerce exists
- **THEN** `disponibles` returns only products whose category, product, and availability flags mark them as available

#### Scenario: Sellable products require priced presentation
- **WHEN** the commerce exists
- **THEN** `vendibles` returns products with an active presentation that has a current price, and only those sellable presentation-price combinations

#### Scenario: Incomplete products report configuration problems
- **WHEN** the commerce exists
- **THEN** `incompletos` returns products with no associations, no active associations, active associations without price, available products without sellable presentation, or products in inactive categories, each with its detected problem codes

### Requirement: Detailed category listing
The system SHALL expose `GET /categorias-productos/{categoria_producto_id}/productos-detalle` and return the category, its products, product-presentation associations, related presentations, and current prices.

#### Scenario: Detailed category listing returns the category tree
- **WHEN** the category exists
- **THEN** the endpoint returns the category, its ordered products, and each product's ordered associations, presentations, and current prices

#### Scenario: Missing category returns 404
- **WHEN** the category does not exist
- **THEN** the endpoint returns `404 Not Found`

### Requirement: Read-only layering and reuse
The system SHALL add the new endpoints through `Router → Service → Repository → SQLAlchemy Model` and SHALL reuse or minimally extend existing product modules. Repositories SHALL NOT commit, roll back, or modify state.

#### Scenario: Read-only access path is preserved
- **WHEN** any new query endpoint is called
- **THEN** no database write or transaction-finalization operation occurs

#### Scenario: Existing lightweight endpoints remain functional
- **WHEN** existing lightweight routes are invoked
- **THEN** they continue to respond as before
