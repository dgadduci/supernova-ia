# Capability: product-alias-persistence

## Purpose

Persist and manage alternate commercial expressions, abbreviations, synonyms, and spelling variants for products and product-presentations so that the fuzzy product recognizer can consume them through a caller-supplied catalog projection rather than a hardcoded production alias map. The capability defines the `producto_aliases` PostgreSQL table and SQLAlchemy model, scoped uniqueness and indexing, repository and service boundaries that keep query code in repositories and leave transaction ownership to the caller, an idempotent seeder that migrates the safely classified hardcoded alias map, and a recognition-ready projection that exposes only the active aliases applicable to the requested products or product-presentations.

## Requirements

### Requirement: Producto alias persistence model

The system SHALL define a `producto_aliases` PostgreSQL table and SQLAlchemy model with a project-standard integer primary key; required `id_producto` foreign key to `productos`; nullable `id_producto_presentacion` foreign key to `producto_presentaciones`; required `alias` and `alias_normalizado`; required `activo` defaulting to true; and project-standard creation and update timestamps. A null `id_producto_presentacion` SHALL represent a product-wide alias and a non-null value SHALL represent an alias for exactly that product-presentation.

#### Scenario: General product alias persists

- **WHEN** a valid alias is created for a product without a product-presentation
- **THEN** it is stored with `id_producto_presentacion` null and is applicable to every catalog row for that product

#### Scenario: Presentation-specific alias persists

- **WHEN** a valid alias is created for a product and one of its product-presentations
- **THEN** it is stored with that product-presentation ID and is applicable only to that exact catalog row

### Requirement: Alias normalization and ownership validation

The alias service SHALL derive `alias_normalizado` using the same text-normalization contract used by the fuzzy recognizer, SHALL reject aliases that normalize to an empty string, and SHALL reject a presentation-specific alias when its `id_producto_presentacion` does not belong to `id_producto`. SQLAlchemy queries SHALL remain in repositories, and alias services SHALL NOT commit, roll back, close, or begin database sessions.

#### Scenario: Empty normalized alias is rejected

- **WHEN** an alias contains no characters after recognizer-compatible normalization
- **THEN** the service rejects it and no alias row is persisted

#### Scenario: Cross-product presentation is rejected

- **WHEN** an alias names product A but references a product-presentation belonging to product B
- **THEN** the service rejects it and no alias row is persisted

#### Scenario: Service leaves transaction ownership to caller

- **WHEN** alias validation or persistence succeeds or fails
- **THEN** the service does not call `commit`, `rollback`, `close`, or `begin`

### Requirement: Duplicate prevention is scoped

The system SHALL prevent duplicate `alias_normalizado` values within the same product-wide scope and within the same product plus product-presentation scope. The system SHALL allow the same normalized alias for different products and SHALL allow such valid shared aliases to produce ambiguity. Nullable-scope uniqueness SHALL be enforced correctly in PostgreSQL rather than relying on null equality in a conventional unique constraint.

#### Scenario: Duplicate product-wide alias is rejected

- **WHEN** the same normalized alias is created twice for one product with no product-presentation
- **THEN** the second row is rejected

#### Scenario: Duplicate presentation alias is rejected

- **WHEN** the same normalized alias is created twice for one product and the same product-presentation
- **THEN** the second row is rejected

#### Scenario: Shared alias across products is allowed

- **WHEN** the same normalized alias is created for two different valid products
- **THEN** both rows persist and recognition may return candidates for both products

### Requirement: Alias indexes and referential integrity

The migration SHALL add indexes supporting `id_producto`, `id_producto_presentacion`, `alias_normalizado`, and `activo` queries, SHALL add foreign keys using existing deletion conventions, and SHALL be reversible without modifying unrelated product or presentation data.

#### Scenario: Alias lookup indexes exist

- **WHEN** PostgreSQL metadata is inspected after migration
- **THEN** indexed access exists for both foreign keys, normalized alias, and activity filtering

#### Scenario: Migration downgrade removes only alias storage

- **WHEN** the alias migration is downgraded
- **THEN** `producto_aliases` and its indexes/constraints are removed without deleting or altering products and product-presentations

### Requirement: Repository and service expose recognition-ready aliases

The repository and service SHALL support alias creation, duplicate/idempotency lookup, lookup by requested product IDs, and lookup by requested product-presentation IDs. Recognition lookup SHALL return only active aliases applicable to the supplied IDs and SHALL batch access without issuing one query per catalog row.

#### Scenario: Requested products receive active general aliases

- **WHEN** recognition aliases are requested for catalog rows belonging to selected product IDs
- **THEN** active product-wide aliases for those products are returned and inactive or unrequested aliases are excluded

#### Scenario: Exact presentation receives specific aliases

- **WHEN** recognition aliases are requested for selected product-presentation IDs
- **THEN** each specific alias is returned only for its exact product-presentation and not for sibling presentations

#### Scenario: Another commerce is excluded

- **WHEN** aliases are loaded for a commerce-scoped catalog
- **THEN** aliases attached to products outside that commerce are not returned

### Requirement: Idempotent alias seeder

The system SHALL expose `backend.scripts.seed_product_aliases`, executable with `PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_aliases`, to migrate every safely classified active hardcoded product alias. The seeder SHALL resolve products and product-presentations using exact stable catalog data rather than database IDs or partial-name matching, SHALL require exactly one safe target per required mapping, SHALL preserve unrelated aliases, and SHALL report inserted, unchanged, skipped, and failed counts.

#### Scenario: First and second runs are idempotent

- **WHEN** the seeder is run twice against the same valid catalog
- **THEN** the first run inserts the expected aliases, the second inserts none, and no duplicate rows exist

#### Scenario: Unsafe ownership aborts required migration

- **WHEN** a required alias target resolves to zero or multiple products or its ownership is otherwise unsafe
- **THEN** the seeder reports the failed mapping and does not silently commit a partial required alias set

#### Scenario: Unrelated alias remains

- **WHEN** an operator-created alias exists before the seeder runs
- **THEN** the seeder neither deletes nor modifies that unrelated row

### Requirement: Only real commercial aliases are persisted

The seeded set SHALL contain only alternate commercial expressions, abbreviations, synonyms, or spelling variants classified as product-wide or product-presentation-specific aliases. Ordinary structured presentation values and the existing presentation extraction vocabulary SHALL NOT be inserted merely because they occur in presentation codes or descriptions.

#### Scenario: Presentation vocabulary is not duplicated

- **WHEN** the seeder processes the current catalog
- **THEN** values such as `chica`, `grande`, `unidad`, and `1 litro` are not inserted solely as product aliases

#### Scenario: Current product spelling aliases are classified

- **WHEN** the active hardcoded product alias map is inventoried
- **THEN** every entry has recorded raw text, normalized text, canonical product ownership, scope type, and compatibility behavior before migration
