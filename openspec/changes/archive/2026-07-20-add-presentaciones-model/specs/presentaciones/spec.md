## ADDED Requirements

### Requirement: Presentacion model definition
The system SHALL define a SQLAlchemy model named `Presentacion` that exposes a primary-key integer `id`; an `id_comercio` Integer ForeignKey (non-null, indexed) pointing to `comercios.id` with `ON DELETE CASCADE`; a non-null `codigo` (String ≤ 50); a non-null `descripcion` (String ≤ 100); an `activo` flag (Boolean, default `True`, server-default `"true"`); an `orden` (Integer, default `0`, server-default `"0"`); lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`); and table-level constraints declaring that within a single comercio the `codigo` and `descripcion` values are each unique, and that `orden` is non-negative.

#### Scenario: Presentacion exposes the required column set
- **WHEN** the `Presentacion` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_comercio` as a non-null Integer ForeignKey to `comercios.id` (indexed)
- **AND** it exposes `codigo` (String ≤ 50, non-null), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: Presentacion cascades on Comercio deletion
- **WHEN** the `Presentacion.id_comercio` foreign key is introspected
- **THEN** it targets `comercios.id`
- **AND** its `ondelete` behavior is set to `CASCADE`

#### Scenario: Presentacion codigo is unique within a comercio
- **WHEN** the `Presentacion` table is introspected for table-level unique constraints
- **THEN** it carries a `UniqueConstraint` named `comercio_presentacion_codigo_unico` whose columns are `id_comercio` and `codigo`

#### Scenario: Presentacion descripcion is unique within a comercio
- **WHEN** the `Presentacion` table is introspected for table-level unique constraints
- **THEN** it carries a `UniqueConstraint` named `comercio_presentacion_descripcion_unica` whose columns are `id_comercio` and `descripcion`

#### Scenario: Presentacion enforces a non-negative orden via check constraint
- **WHEN** the `Presentacion` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `orden_no_negativo` whose SQL expression is `orden >= 0`

#### Scenario: Presentacion table name
- **WHEN** the `Presentacion` model is introspected for its table identifier
- **THEN** the table name is `presentaciones`
