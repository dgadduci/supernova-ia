# Capability: medios-pago

## Purpose

Define the `MediosPago` SQLAlchemy model — the reference catalog of payment methods a commerce may offer its customers. Holds a unique `codigo`, a human-readable `descripcion`, an `activo` flag for soft-disable, and lifecycle timestamps. Consumers (e.g., a commerce–payment association) will land in later subphases.

## Requirements

### Requirement: MediosPago model definition
The system SHALL define a SQLAlchemy model named `MediosPago` that exposes a primary-key integer `id`; a unique, indexed `codigo` (String ≤ 50); a non-null `descripcion` (String ≤ 100); an `activo` flag (Boolean, default `True`, server-default `"true"`); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (both timezone-aware DateTime with `server_default=now()`, the latter additionally `onupdate=now()`).

#### Scenario: MediosPago exposes the required column set
- **WHEN** the `MediosPago` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `codigo` (String ≤ 50, non-null, unique, indexed), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`) and `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`)

#### Scenario: MediosPago table name
- **WHEN** the `MediosPago` model is introspected for its table identifier
- **THEN** the table name is `medios_pago`
