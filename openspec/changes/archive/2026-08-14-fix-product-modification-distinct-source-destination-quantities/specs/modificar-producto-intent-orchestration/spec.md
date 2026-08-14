## ADDED Requirements

### Requirement: Paired quantities survive modification clarification

The initial orchestrator and `product_modification_resolver` SHALL retain an
optional `cantidad_destino` unchanged in ready and pending `resolved_data`.
Source and destination candidate refinement remains identity-only and SHALL
not replace either amount.

#### Scenario: Destination selection keeps a 2 to 1 request

- **WHEN** `cambiar dos napolitanas grandes por una pizza de mozzarella` creates destination-selection pending state
- **THEN** its `resolved_data` contains `cantidad == 2` and `cantidad_destino == 1`; after `chica` selects one persisted candidate, the ready intent preserves both values

#### Scenario: Old pending payload remains executable

- **WHEN** an active modification pending intent contains legacy `cantidad` and no `cantidad_destino`
- **THEN** resolving its candidate retains existing equal-quantity semantics and does not reject solely because the new optional field is absent
