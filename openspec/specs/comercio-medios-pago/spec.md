# Capability: comercio-medios-pago

## Purpose

Define the `ComercioMedioPago` SQLAlchemy model — the join table that ties a `Comercio` to the payment methods it accepts from the global `MediosPago` catalog introduced in Subphase 1.3. Each row represents one (comercio, medio de pago) pair; a composite uniqueness rule ensures no duplicates, an opt-in `activo` flag (default `false`) governs whether the pair is currently enabled, two per-comercio nullable metadata columns (`titular`, `alias`) carry operator-facing display info that does not belong on the global catalog, and lifecycle timestamps track creation and modification. Unlike `ComercioMetodoEntrega` (Subphase 1.9), this join has no `orden` column and therefore no `CheckConstraint`. Bidirectional `comercio` and `medio_pago` relationships expose the join; the corresponding `Comercio.medios_pago` and `MediosPago.comercios` collections are introduced here.

## Requirements

### Requirement: ComercioMedioPago model definition
The system SHALL define a SQLAlchemy model named `ComercioMedioPago` that exposes a primary-key integer `id`; a non-null `id_comercio` foreign key to `comercios.id` with `ondelete="CASCADE"` and an index; a non-null `id_medio_pago` foreign key to `medios_pago.id` with `ondelete="RESTRICT"` and an index; a non-null `activo` Boolean with `default=False` and `server_default="false"`; a nullable `titular` String ≤ 150 (no default); a nullable `alias` String ≤ 100 (no default); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: ComercioMedioPago exposes the required column set
- **WHEN** the `ComercioMedioPago` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `id_comercio` as a non-null integer ForeignKey to `comercios.id` with `ondelete="CASCADE"` and `index=True`
- **AND** it exposes `id_medio_pago` as a non-null integer ForeignKey to `medios_pago.id` with `ondelete="RESTRICT"` and `index=True`
- **AND** it exposes `activo` as a non-null Boolean with `default=False` and `server_default="false"`
- **AND** it exposes `titular` as a nullable String ≤ 150 with no default
- **AND** it exposes `alias` as a nullable String ≤ 100 with no default
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: ComercioMedioPago enforces uniqueness per (comercio, medio de pago)
- **WHEN** the `ComercioMedioPago` table is introspected for table-level unique constraints
- **THEN** it carries a unique constraint named `comercio_medio_pago_unico` over `(id_comercio, id_medio_pago)`

#### Scenario: ComercioMedioPago has no orden column and no check constraint
- **WHEN** the `ComercioMedioPago` table is introspected for its column set and table-level check constraints
- **THEN** it does not expose an `orden` column
- **AND** it carries no `CheckConstraint` on the table

#### Scenario: ComercioMedioPago table name
- **WHEN** the `ComercioMedioPago` model is introspected for its table identifier
- **THEN** the table name is `comercio_medios_pago`

### Requirement: Bidirectional relationship to Comercio
The system SHALL declare `ComercioMedioPago.comercio` as a `Mapped["Comercio"]` relationship that `back_populates="medios_pago"`, and SHALL declare the corresponding `Comercio.medios_pago` as a `Mapped[list["ComercioMedioPago"]]` relationship that `back_populates="comercio"`.

#### Scenario: Navigation from join row to parent comercio
- **WHEN** the `ComercioMedioPago.comercio` relationship is resolved
- **THEN** it returns a `Comercio` instance corresponding to `id_comercio`

#### Scenario: Navigation from a comercio to its medio-de-pago join rows
- **WHEN** the `Comercio.medios_pago` relationship is resolved
- **THEN** it returns a list of `ComercioMedioPago` instances whose `id_comercio` equals the parent `Comercio.id`

### Requirement: Bidirectional relationship to MediosPago
The system SHALL declare `ComercioMedioPago.medio_pago` as a `Mapped["MediosPago"]` relationship that `back_populates="comercios"`, and SHALL declare the corresponding `MediosPago.comercios` as a `Mapped[list["ComercioMedioPago"]]` relationship that `back_populates="medio_pago"`.

#### Scenario: Navigation from join row to catalog medio de pago
- **WHEN** the `ComercioMedioPago.medio_pago` relationship is resolved
- **THEN** it returns a `MediosPago` instance corresponding to `id_medio_pago`

#### Scenario: Navigation from a catalog medio de pago to its comercios
- **WHEN** the `MediosPago.comercios` relationship is resolved
- **THEN** it returns a list of `ComercioMedioPago` instances whose `id_medio_pago` equals the parent `MediosPago.id`
