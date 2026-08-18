# Capability: estado-comercio

## Purpose

Define the `EstadoComercio` SQLAlchemy model used as the reference table for commerce status in the multi-commerce WhatsApp ordering system.
## Requirements
### Requirement: EstadoComercio model definition
The system SHALL define a SQLAlchemy model named `EstadoComercio` that exposes a primary-key integer column `id` and a non-null string column `estado`.

#### Scenario: EstadoComercio exposes the required columns
- **WHEN** the `EstadoComercio` model is imported and its columns are inspected
- **THEN** it exposes a column named `id` of integer type that is the table primary key
- **AND** it exposes a non-null column named `estado` of string type

### Requirement: Commerce state has an explicit operating mode

Each `EstadoComercio` SHALL expose a unique stable `codigo`, an
operator-facing `descripcion`, a typed `modo_operacion`, and a
`seleccionable` flag. The policy SHALL make operational decisions from
`modo_operacion`, never from code or description. The initial selectable
configuration SHALL provide ACTIVO/HABILITADO, INACTIVO/BLOQUEADO, and
PRUEBA/PRUEBA, but no caller SHALL hardcode those codes as a behavior branch.

#### Scenario: Display text does not govern availability

- **WHEN** an operator-facing state description changes without changing its
  operating mode
- **THEN** the availability outcome is unchanged

### Requirement: Legacy blocked states preserve existing references

Existing non-canonical status rows SHALL be retained, assigned BLOCKED mode,
and marked non-selectable during this change. They SHALL not be selectable for
a new commerce or an admin state update.

#### Scenario: Legacy BAJA status remains fail-closed

- **WHEN** an existing commerce references the legacy BAJA row
- **THEN** its reference remains valid
- **AND** the availability policy returns unavailable
