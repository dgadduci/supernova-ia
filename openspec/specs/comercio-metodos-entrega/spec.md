# Capability: comercio-metodos-entrega

## Purpose

Define the `ComercioMetodoEntrega` SQLAlchemy model — the join table that ties a `Comercio` to the delivery methods it accepts from the global `MetodosEntrega` catalog introduced in Subphase 1.4. Each row represents one (comercio, method) pair; a composite uniqueness rule ensures no duplicates, an opt-in `activo` flag (default `false`) governs whether the pair is currently enabled, a non-negative `orden` controls display order, and a DB-level `CheckConstraint` prevents negative ordering values. Bidirectional `comercio` and `metodo_entrega` relationships expose the join; the corresponding `Comercio.metodos_entrega` and `MetodosEntrega.comercios` collections are re-introduced here after being deferred from earlier subphases.

## Requirements

### Requirement: ComercioMetodoEntrega model definition
The system SHALL define a SQLAlchemy model named `ComercioMetodoEntrega` that exposes a primary-key integer `id`; a non-null `id_comercio` foreign key to `comercios.id` with `ondelete="CASCADE"` and an index; a non-null `id_metodo_entrega` foreign key to `metodos_entrega.id` with `ondelete="RESTRICT"` and an index; a non-null `activo` Boolean with `default=False` and `server_default="false"`; a non-null `orden` Integer (no Python-side or server-side default); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: ComercioMetodoEntrega exposes the required column set
- **WHEN** the `ComercioMetodoEntrega` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_comercio` as a non-null integer ForeignKey to `comercios.id` with `ondelete="CASCADE"` and `index=True`
- **AND** it exposes `id_metodo_entrega` as a non-null integer ForeignKey to `metodos_entrega.id` with `ondelete="RESTRICT"` and `index=True`
- **AND** it exposes `activo` as a non-null Boolean with `default=False` and `server_default="false"`
- **AND** it exposes `orden` as a non-null Integer with no default (inserts must supply it explicitly)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: ComercioMetodoEntrega enforces uniqueness per (comercio, method)
- **WHEN** the `ComercioMetodoEntrega` table is introspected for table-level unique constraints
- **THEN** it carries a unique constraint named `comercio_metodo_unico` over `(id_comercio, id_metodo_entrega)`

#### Scenario: ComercioMetodoEntrega enforces a non-negative orden via check constraint
- **WHEN** the `ComercioMetodoEntrega` table is introspected for table-level check constraints
- **THEN** it carries a check constraint named `orden_no_negativo` whose SQL expression is `orden >= 0`

#### Scenario: ComercioMetodoEntrega table name
- **WHEN** the `ComercioMetodoEntrega` model is introspected for its table identifier
- **THEN** the table name is `comercio_metodos_entrega`

### Requirement: Bidirectional relationship to Comercio
The system SHALL declare `ComercioMetodoEntrega.comercio` as a `Mapped["Comercio"]` relationship that `back_populates="metodos_entrega"`, and SHALL declare the corresponding `Comercio.metodos_entrega` as a `Mapped[list["ComercioMetodoEntrega"]]` relationship that `back_populates="comercio"`.

#### Scenario: Navigation from join row to parent comercio
- **WHEN** the `ComercioMetodoEntrega.comercio` relationship is resolved
- **THEN** it returns a `Comercio` instance corresponding to `id_comercio`

#### Scenario: Navigation from a comercio to its method join rows
- **WHEN** the `Comercio.metodos_entrega` relationship is resolved
- **THEN** it returns a list of `ComercioMetodoEntrega` instances whose `id_comercio` equals the parent `Comercio.id`

### Requirement: Bidirectional relationship to MetodosEntrega
The system SHALL declare `ComercioMetodoEntrega.metodo_entrega` as a `Mapped["MetodosEntrega"]` relationship that `back_populates="comercios"`, and SHALL declare the corresponding `MetodosEntrega.comercios` as a `Mapped[list["ComercioMetodoEntrega"]]` relationship that `back_populates="metodo_entrega"`.

#### Scenario: Navigation from join row to catalog method
- **WHEN** the `ComercioMetodoEntrega.metodo_entrega` relationship is resolved
- **THEN** it returns a `MetodosEntrega` instance corresponding to `id_metodo_entrega`

#### Scenario: Navigation from a catalog method to its comercios
- **WHEN** the `MetodosEntrega.comercios` relationship is resolved
- **THEN** it returns a list of `ComercioMetodoEntrega` instances whose `id_metodo_entrega` equals the parent `MetodosEntrega.id`
