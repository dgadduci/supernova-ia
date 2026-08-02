## ADDED Requirements

### Requirement: MetodosEntrega model definition
The system SHALL define a SQLAlchemy model named `MetodosEntrega` that exposes a primary-key integer `id`; a unique, indexed `codigo` (String ≤ 50); a non-null `descripcion` (String ≤ 100); a non-null `orden` (Integer) constrained to be greater than or equal to zero by a table-level check constraint named `orden_no_negativo`; an `activo` flag (Boolean, default `True`, server-default `"true"`); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: MetodosEntrega exposes the required column set
- **WHEN** the `MetodosEntrega` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `codigo` (String ≤ 50, non-null, unique, indexed), `descripcion` (String ≤ 100, non-null), `orden` (Integer, non-null), and `activo` (Boolean, non-null, default `True`, server-default `"true"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: MetodosEntrega enforces a non-negative orden via check constraint
- **WHEN** the `MetodosEntrega` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `orden_no_negativo` whose SQL expression is `orden >= 0`

#### Scenario: MetodosEntrega table name
- **WHEN** the `MetodosEntrega` model is introspected for its table identifier
- **THEN** the table name is `metodos_entrega`
