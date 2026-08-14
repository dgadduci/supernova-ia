## ADDED Requirements

### Requirement: Atomic distinct source and destination amounts

`PedidoProductoService.modify_product` SHALL accept an effective source amount
and optional destination amount. When the destination amount is present and
positive, it SHALL decrement/delete source by the source amount and
create/increment destination by the destination amount in the same existing
caller-owned transaction. When absent, destination SHALL receive the effective
source amount for backward compatibility.

#### Scenario: Partial 2 to 1 modification

- **WHEN** a source line contains 7 units and a ready intent requests source `cantidad == 2` and `cantidad_destino == 1`
- **THEN** source becomes 5, destination increases by 1, and no commit or rollback is issued by recognizer, resolver, handler, or service

#### Scenario: Source ceiling still governs the mutation

- **WHEN** source `cantidad` exceeds its current line, regardless of a lower valid `cantidad_destino`
- **THEN** the result is the existing `quantity_exceeds_source` rejection and neither line changes

#### Scenario: Existing one-quantity request remains equal transfer

- **WHEN** a ready intent has `cantidad == 2` and no `cantidad_destino`
- **THEN** source decreases by 2 and destination increases by 2 exactly as before
