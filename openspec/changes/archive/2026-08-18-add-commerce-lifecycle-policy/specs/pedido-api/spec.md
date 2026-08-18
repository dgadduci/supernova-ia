## ADDED Requirements

### Requirement: Confirmed orders reserve trial quota atomically

Every transition of a comercio's pedido from `BORRADOR` to `INGRESADO` SHALL
re-evaluate availability. For a PRUEBA commerce it SHALL lock and reserve one
quota unit in the same caller-owned transaction as the state transition. The
reservation SHALL not commit independently.

#### Scenario: Final trial quota admits only one concurrent confirmation

- **WHEN** two confirmations race while exactly one trial quota unit remains
- **THEN** exactly one pedido becomes INGRESADO and increments consumption
- **AND** the other remains non-confirmed with a typed unavailable outcome

#### Scenario: Failed confirmation does not consume quota

- **WHEN** a technical failure rolls back a confirmation after a trial
  reservation was staged
- **THEN** neither the pedido transition nor the counter increment persists
