# Capability: producto-presentacion

## Purpose

Define the `ProductoPresentacion` SQLAlchemy model — a join row between `productos` and `presentaciones` recording which products are offered in which per-comercio presentations. Holds the FKs, the `activo` flag, the `orden` integer, and lifecycle timestamps. A composite uniqueness rule prevents duplicate `(id_producto, id_presentacion)` pairs and a non-negative-order check constrains `orden`. Serves as the parent of zero or more `Precio` rows (1:1 enforced via unique index on the FK side).

## Requirements

### Requirement: ProductoPresentacion model definition
The system SHALL define a SQLAlchemy model named `ProductoPresentacion` that exposes a primary-key integer `id`; an `id_producto` Integer ForeignKey (non-null, indexed) pointing to `productos.id` with `ON DELETE CASCADE`; an `id_presentacion` Integer ForeignKey (non-null, indexed) pointing to `presentaciones.id` with `ON DELETE CASCADE`; a non-null `activo` flag (Boolean, default `True`, server-default `"true"`); a non-null `orden` (Integer, default `0`, server-default `"0"`); lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`); a unique `(id_producto, id_presentacion)` composite constraint named `producto_presentacion_unico`; a non-negative-order check constraint named `orden_no_negativo`; a `precios` one-to-many relationship to a list of `Precio` instances; and an `embeddings` one-to-many relationship to product-presentation embedding instances. Deleting a product presentation SHALL cascade to its embedding rows.

#### Scenario: ProductoPresentacion exposes the required column set
- **WHEN** the `ProductoPresentacion` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_producto` (Integer, non-null, ForeignKey to `productos.id`, indexed), `id_presentacion` (Integer, non-null, ForeignKey to `presentaciones.id`, indexed)
- **AND** it exposes `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: ProductoPresentacion cascades on Producto and on Presentacion
- **WHEN** the `ProductoPresentacion.id_producto` foreign key is introspected
- **THEN** it targets `productos.id`
- **AND** its `ondelete` behavior is set to `CASCADE`
- **WHEN** the `ProductoPresentacion.id_presentacion` foreign key is introspected
- **THEN** it targets `presentaciones.id`
- **AND** its `ondelete` behavior is set to `CASCADE`

#### Scenario: ProductoPresentacion enforces unique (id_producto, id_presentacion)
- **WHEN** the `ProductoPresentacion` table is introspected for table-level unique constraints
- **THEN** it carries a `UniqueConstraint` named `producto_presentacion_unico` whose columns are `id_producto` and `id_presentacion`

#### Scenario: ProductoPresentacion enforces a non-negative orden via check constraint
- **WHEN** the `ProductoPresentacion` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `orden_no_negativo` whose SQL expression is `orden >= 0`

#### Scenario: ProductoPresentacion exposes its precios relationship
- **WHEN** the `ProductoPresentacion` model is introspected for relationships
- **THEN** it exposes a `precios` relationship that resolves to a list of `Precio` instances

#### Scenario: ProductoPresentacion exposes its embeddings relationship
- **WHEN** the `ProductoPresentacion` model is introspected for relationships
- **THEN** it exposes an `embeddings` relationship that resolves to a list of product-presentation embedding instances
- **AND** deleting the parent removes associated embedding rows

#### Scenario: ProductoPresentacion table name
- **WHEN** the `ProductoPresentacion` model is introspected for its table identifier
- **THEN** the table name is `producto_presentaciones`
