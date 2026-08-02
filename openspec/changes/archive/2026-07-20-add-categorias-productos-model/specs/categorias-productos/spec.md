## ADDED Requirements

### Requirement: CategoriasProductos model definition
The system SHALL define a SQLAlchemy model named `CategoriasProductos` that exposes a primary-key integer `id`; an `id_comercio` Integer ForeignKey (non-null, indexed) pointing to `comercios.id` with `ON DELETE CASCADE`; a non-null `descripcion` (String ≤ 100); an `activo` flag (Boolean, default `True`, server-default `"true"`); an `orden` (Integer, default `0`, server-default `"0"`); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: CategoriasProductos exposes the required column set
- **WHEN** the `CategoriasProductos` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_comercio` as a non-null Integer ForeignKey to `comercios.id` (indexed)
- **AND** it exposes `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: CategoriasProductos cascades on Comercio deletion
- **WHEN** the `CategoriasProductos.id_comercio` foreign key is introspected
- **THEN** it targets `comercios.id`
- **AND** its `ondelete` behavior is set to `CASCADE`

#### Scenario: CategoriasProductos table name
- **WHEN** the `CategoriasProductos` model is introspected for its table identifier
- **THEN** the table name is `categorias_productos`
