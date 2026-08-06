## MODIFIED Requirements

### Requirement: Presentation aliases exclude product descriptors

`PRESENTACION_ALIASES` SHALL contain only terms that represent a structured
catalog presentation for the current recognition path. A product descriptor
that occurs in `producto_nombre` but is not a catalog presentation SHALL NOT
activate presentation filtering. In particular, `picante` SHALL NOT be a key
in `PRESENTACION_ALIASES`; recognizing `empanadas carne picante` against an
active `Empanada de Carne Picante` with presentation `unidad` SHALL retain
that candidate through the normal fuzzy path.

#### Scenario: Product descriptor does not filter its own candidate

- **WHEN** the catalog contains `Empanada de Carne Picante` with
  `presentacion_codigo == "unidad"`
- **AND** the customer text is `empanadas carne picante`
- **THEN** the recognizer retains the unit candidate
- **AND** `picante` is not treated as a presentation alias

#### Scenario: Legitimate presentation aliases remain active

- **WHEN** the input includes an existing legitimate presentation term such as
  `grande`, `chica`, or `lata`
- **THEN** existing presentation filtering behavior is unchanged
