## ADDED Requirements

### Requirement: ProductoPresentacion model definition
The system SHALL define a SQLAlchemy model named `ProductoPresentacion` that exposes a primary-key integer `id`; an `id_producto` Integer ForeignKey (non-null, indexed) pointing to `productos.id` with `ON DELETE CASCADE`; an `id_presentacion` Integer ForeignKey (non-null, indexed) pointing to `presentaciones.id` with `ON DELETE CASCADE`; a non-null `activo` flag (Boolean, default `True`, server-default `"true"`); a non-null `orden` (Integer, default `0`, server-default `"0"`); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`). This requirement captures the **stub** shape only; a later subphase refines the schema.

#### Scenario: ProductoPresentacion exposes the stub column set
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

#### Scenario: ProductoPresentacion table name
- **WHEN** the `ProductoPresentacion` model is introspected for its table identifier
- **THEN** the table name is `producto_presentacion`
