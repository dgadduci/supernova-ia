## ADDED Requirements

### Requirement: Guided closure operates only on the associated draft

The inbound message pipeline SHALL resolve closure actions only against the active conversation session's associated `borrador` pedido. It SHALL NOT create, replace, reassociate, or select another pedido. Missing association or a non-borrador pedido SHALL be a deterministic non-mutating business outcome.

#### Scenario: A foreign pedido cannot be selected

- **WHEN** a customer sends any guided-closure intent
- **THEN** the pipeline uses only the pedido referenced by the active session
- **AND** it does not read or mutate a pedido belonging to another session

### Requirement: Summary describes persisted draft state

The system SHALL respond to `consultar_resumen_pedido` with current persisted draft lines and selected payment/delivery choices, without changing the pedido, line items, session, pending contexts, or state.

#### Scenario: Empty draft requests guidance

- **WHEN** the associated borrador has no line items
- **THEN** the response states that products must be added before confirmation
- **AND** no persisted state changes

### Requirement: Payment and delivery choices are commerce-scoped

For `set_metodo_de_pago` and `set_metodo_de_entrega`, the system SHALL mutate a borrador only after a unique normalized choice matches an active catalog association for that commerce. Unknown, ambiguous, inactive, or other-commerce choices SHALL leave the pedido unchanged and request scoped clarification.

#### Scenario: Foreign payment choice is rejected without mutation

- **WHEN** a payment method exists globally but is not active for the session's commerce
- **THEN** the pedido's payment selection remains unchanged
- **AND** the response asks for one enabled choice

### Requirement: Explicit confirmation requires a complete non-empty draft

`confirmar_pedido` SHALL transition only a `borrador` with one or more lines, an active commerce-scoped payment selection, and an active commerce-scoped delivery selection to `ingresado`. Every missing prerequisite or a non-borrador state SHALL yield guidance without mutation.

#### Scenario: Complete draft confirms once

- **WHEN** a draft has lines and valid selected payment and delivery choices
- **THEN** confirmation persists `borrador → ingresado`
- **AND** a later confirmation cannot create another transition or duplicate effects

### Requirement: Closure preserves the existing transaction boundary

Guided closure components SHALL NOT call transaction-control methods. A technical failure during a closure turn SHALL propagate to the existing local or deferred provider transaction owner, which rolls back the complete turn.

#### Scenario: Provider technical failure rolls back closure mutation

- **WHEN** deferred processing raises after staging a closure mutation and before final commit
- **THEN** selected fields and pedido state are not durable
- **AND** existing work-item retry/failure handling remains authoritative
