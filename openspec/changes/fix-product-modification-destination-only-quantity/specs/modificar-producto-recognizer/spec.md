## ADDED Requirements

### Requirement: Destination-only quantity means full source replacement

When a modification message has no explicit positive quantity before `por` and
one explicit positive quantity after it, the recognizer SHALL emit
`cantidad is None` and `cantidad_destino == M`. It SHALL not copy M into
legacy source `cantidad`.

#### Scenario: Full one-unit source becomes two destination units

- **WHEN** the message is `cambia la napolitana grande por dos mozzarella grande` and the selected source line has quantity 1
- **THEN** the ready intent preserves `cantidad is None` and `cantidad_destino == 2`, so execution removes the source line and adds 2 destination units

#### Scenario: Legacy pending remains unchanged

- **WHEN** an existing pending payload has `cantidad == 2` and no `cantidad_destino`
- **THEN** it continues to mean source 2 -> destination 2
