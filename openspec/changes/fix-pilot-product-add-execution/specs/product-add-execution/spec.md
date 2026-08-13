## ADDED Requirements

### Requirement: Modern product add is staged in the caller transaction

The modern `agregar_producto` handler SHALL use a dedicated caller-owned
service seam that validates the active session's own `borrador` Pedido,
selected presentation, positive quantity and exactly one current price before
staging one create or increment. The seam SHALL NOT commit, rollback, begin,
close, refresh or flush. It SHALL NOT select a presentation outside the
resolved candidate set or infer a price.

#### Scenario: Resolved priced presentation creates one line

- **WHEN** `Grande` resolves to a selected candidate of the active session's
  own draft Pedido and that presentation has exactly one current price
- **THEN** the handler returns `executed` and stages one line with that price
  snapshot
- **AND** the outer provider transaction remains the only transaction owner

#### Scenario: Missing or ambiguous price rejects without mutation

- **WHEN** the selected presentation has zero or more than one current price
- **THEN** the handler returns `rejected`, creates or changes no order line
- **AND** it does not choose another price or presentation

### Requirement: Legacy product-add transaction contract remains isolated

The dedicated modern seam SHALL NOT change existing public `add_or_increment`
behavior used by legacy callers. The modern handler SHALL NOT invoke that
legacy transaction-owning method.

#### Scenario: Modern provider turn does not commit during handler execution

- **WHEN** the real provider coordinator processes a successful selected
  product turn
- **THEN** no handler/service transaction-control call occurs before the
  coordinator commits the complete turn
