## ADDED Requirements

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
