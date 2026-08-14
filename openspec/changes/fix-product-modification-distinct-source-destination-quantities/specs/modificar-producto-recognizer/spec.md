## ADDED Requirements

### Requirement: Explicit paired source and destination quantities

When a `modificar_producto` message has the existing `por` separator and
contains an explicit positive quantity on both sides, the recognizer SHALL
emit the source amount as `cantidad` and the destination amount as optional
`cantidad_destino`. It SHALL derive both only with the existing normalized
quantity vocabulary; no LLM, hybrid, or candidate result may supply them.

#### Scenario: Two source units become one destination unit

- **WHEN** the message is `cambiar dos napolitanas grandes por una pizza de mozzarella`
- **THEN** the recognizer emits `cantidad == 2` and `cantidad_destino == 1`

#### Scenario: One explicit quantity remains compatible

- **WHEN** the message is `cambiar dos napolitanas grandes por mozzarella`
- **THEN** `cantidad == 2` and `cantidad_destino is None`, preserving the existing equal-quantity transfer contract
