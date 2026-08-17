## ADDED Requirements

### Requirement: Update a global delivery method through the shared service

The system SHALL provide a typed global delivery-method update operation that
resolves one exact `MetodosEntrega` row and may update its `descripcion`,
global `orden`, and `activo`. It SHALL keep `codigo` immutable, trim and
reject an empty description, reject an order below zero, and own one atomic
commit/rollback transaction. The operation SHALL NOT modify
`ComercioMetodoEntrega` or `Pedido` rows.

#### Scenario: Valid update preserves commerce-scoped ordering

- **WHEN** an operator updates global delivery method D with a new global
  description, order, or active state
- **THEN** only D is changed
- **AND** every `ComercioMetodoEntrega` associated with D retains its prior
  `activo` and commerce-specific `orden`
- **AND** every existing `Pedido.id_metodo_entrega` retains its prior value

#### Scenario: Invalid or failed update is atomic

- **WHEN** the global update has an empty normalized description, an order
  below zero, an unknown ID, or a persistence failure
- **THEN** the prior global row remains unchanged
- **AND** no bridge row or order is modified
- **AND** any failed persistence transaction is rolled back
