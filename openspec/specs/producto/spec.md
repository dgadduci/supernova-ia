# Capability: producto

## Purpose

Define the `Producto` SQLAlchemy model — the per-category product row carrying `nombre`, an optional `descripcion` (`Text`, nullable), separate `activo` (catalog-active) and `disponible` (in-stock) flags, an `orden` constrained `>= 0`, lifecycle timestamps, a foreign key to `categorias_productos.id` with `ON DELETE RESTRICT`, a unique `(id_categoria_producto, nombre)` per-category constraint, and relationships to `CategoriaProducto` (many-to-one) and `ProductoPresentacion` (one-to-many).

## Requirements

### Requirement: Producto model definition
The system SHALL define a SQLAlchemy model named `Producto` that exposes a primary-key integer `id`; an `id_categoria_producto` Integer ForeignKey (non-null, indexed) pointing to `categorias_productos.id` with `ON DELETE RESTRICT`; a non-null `nombre` (String ≤ 150); a nullable `descripcion` (Text); a non-null `activo` flag (Boolean, default `True`, server-default `"true"`); a non-null `disponible` flag (Boolean, default `True`, server-default `"true"`); a non-null `orden` (Integer, default `0`, server-default `"0"`); lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`); a non-negative-order check constraint named `orden_no_negativo`; a composite unique `(id_categoria_producto, nombre)` constraint named `categoria_producto_nombre_unico`; a `categoria` relationship to a `CategoriaProducto` row; and a `presentaciones` relationship to a list of `ProductoPresentacion` rows.

#### Scenario: Producto exposes the required column set
- **WHEN** the `Producto` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_categoria_producto` as a non-null Integer ForeignKey to `categorias_productos.id` (indexed)
- **AND** it exposes `nombre` (String ≤ 150, non-null), `descripcion` (Text, nullable), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `disponible` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: Producto restricts delete on CategoriaProducto
- **WHEN** the `Producto.id_categoria_producto` foreign key is introspected
- **THEN** it targets `categorias_productos.id`
- **AND** its `ondelete` behavior is set to `RESTRICT`

#### Scenario: Producto nombre is unique within a CategoriaProducto
- **WHEN** the `Producto` table is introspected for table-level unique constraints
- **THEN** it carries a `UniqueConstraint` named `categoria_producto_nombre_unico` whose columns are `id_categoria_producto` and `nombre`

#### Scenario: Producto enforces a non-negative orden via check constraint
- **WHEN** the `Producto` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `orden_no_negativo` whose SQL expression is `orden >= 0`

#### Scenario: Producto exposes its relationships
- **WHEN** the `Producto` model is introspected for relationships
- **THEN** it exposes a `categoria` relationship that resolves to a `CategoriaProducto` instance
- **AND** it exposes a `presentaciones` relationship that resolves to a list of `ProductoPresentacion` instances

#### Scenario: Producto table name
- **WHEN** the `Producto` model is introspected for its table identifier
- **THEN** the table name is `productos`
