# Capability: categorias-productos

## Purpose

Define the `CategoriaProducto` SQLAlchemy model — the per-commerce product-category configuration table. Each row records a local description, activation flag, display order and lifecycle timestamps under one parent `Comercio` (cascade-deleted) and serves as the parent of a `Producto` collection.

## Requirements

### Requirement: CategoriaProducto model definition
The system SHALL define a SQLAlchemy model named `CategoriaProducto` that exposes a primary-key integer `id`; an `id_comercio` Integer ForeignKey (non-null, indexed) pointing to `comercios.id` with `ON DELETE CASCADE`; a non-null `descripcion` (String ≤ 100); an `activo` flag (Boolean, default `True`, server-default `"true"`); an `orden` (Integer, default `0`, server-default `"0"`); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: CategoriaProducto exposes the required column set
- **WHEN** the `CategoriaProducto` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_comercio` as a non-null Integer ForeignKey to `comercios.id` (indexed)
- **AND** it exposes `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: CategoriaProducto cascades on Comercio deletion
- **WHEN** the `CategoriaProducto.id_comercio` foreign key is introspected
- **THEN** it targets `comercios.id`
- **AND** its `ondelete` behavior is set to `CASCADE`

#### Scenario: CategoriaProducto exposes its productos relationship
- **WHEN** the `CategoriaProducto` model is introspected for relationships
- **THEN** it exposes a `productos` relationship that resolves to a list of `Producto` instances

#### Scenario: CategoriaProducto table name
- **WHEN** the `CategoriaProducto` model is introspected for its table identifier
- **THEN** the table name is `categorias_productos`
