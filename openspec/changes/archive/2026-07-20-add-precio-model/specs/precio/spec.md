## ADDED Requirements

### Requirement: Precio model definition
The system SHALL define a SQLAlchemy model named `Precio` that exposes a primary-key integer `id`; an `id_producto_presentacion` Integer ForeignKey (non-null, indexed) pointing to `producto_presentaciones.id` with `ON DELETE RESTRICT`; a non-null `precio` (`Decimal` via `Numeric(12, 2)`); a lifecycle timestamp `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`); a non-negative-price check constraint named `precio_no_negativo`; a unique index on `id_producto_presentacion` named `id_producto_presentacion`; and a `producto_presentacion` relationship to a `ProductoPresentacion` instance.

#### Scenario: Precio exposes the required column set
- **WHEN** the `Precio` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_producto_presentacion` (Integer, non-null, ForeignKey to `producto_presentaciones.id`, indexed), `precio` (Decimal via `Numeric(12, 2)`, non-null), and `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`)

#### Scenario: Precio restricts delete on ProductoPresentacion
- **WHEN** the `Precio.id_producto_presentacion` foreign key is introspected
- **THEN** it targets `producto_presentaciones.id`
- **AND** its `ondelete` behavior is set to `RESTRICT`

#### Scenario: Precio enforces a non-negative precio via check constraint
- **WHEN** the `Precio` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `precio_no_negativo` whose SQL expression is `precio >= 0`

#### Scenario: Precio enforces one price per ProductoPresentacion via unique index
- **WHEN** the `Precio` table is introspected for indexes
- **THEN** it carries a unique index named `id_producto_presentacion` on the `id_producto_presentacion` column

#### Scenario: Precio exposes its relationship to ProductoPresentacion
- **WHEN** the `Precio` model is introspected for relationships
- **THEN** it exposes a `producto_presentacion` relationship that resolves to a `ProductoPresentacion` instance

#### Scenario: Precio table name
- **WHEN** the `Precio` model is introspected for its table identifier
- **THEN** the table name is `producto_precios`
