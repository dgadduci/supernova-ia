## MODIFIED Requirements

### Requirement: Presentation matching against presentacion_codigo and presentacion_descripcion
The function SHALL match legitimate presentation terms against the catalog item's `presentacion_codigo` and `presentacion_descripcion` after the product name match. A recognized presentation-specific term in the user text SHALL restrict the match to the corresponding presentation. Flavor, variety, ingredient, and product-descriptor terms that are part of `producto_nombre`, including `picante`, SHALL NOT be classified as presentation aliases and SHALL NOT discard a matching product candidate because its `presentacion_codigo` lacks that term. Existing recognition for legitimate presentation concepts, including `chica`, `mediana`, `grande`, `unidad`, `porción`, `docena`, `media docena`, `litro`, and `medio litro`, SHALL remain available.

#### Scenario: Explicit presentation resolves one candidate
- **WHEN** the test calls the function with a text containing a legitimate presentation term such as `grande` and a catalog with multiple presentations of the same product
- **THEN** only the candidate whose `presentacion_codigo` or `presentacion_descripcion` represents that presentation remains eligible for a confident match

#### Scenario: Product descriptor does not activate presentation filtering
- **WHEN** the test calls the function with `empanadas carne picante` and the supplied catalog contains an eligible product-presentation whose `producto_nombre` is `Empanada de Carne Picante` and whose structured presentation is `unidad`
- **THEN** the candidate is not discarded because its `presentacion_codigo` does not contain `picante`, and the expected destination can resolve

#### Scenario: Legitimate presentation vocabulary remains recognized
- **WHEN** the input identifies a catalog product together with a legitimate size, unit, portion, dozen, liter, or half-liter presentation term represented by the supplied catalog
- **THEN** presentation matching continues to restrict candidates according to the corresponding `presentacion_codigo` or `presentacion_descripcion`

#### Scenario: Unknown presentation text does not create a false product match
- **WHEN** user text contains an unknown term that neither identifies a supplied product nor represents one of its structured presentations
- **THEN** the term does not create a recognized product-presentation candidate and the unmatched fragment remains in `no_encontrados`

#### Scenario: Omitted-quantity replacement resolves descriptor-bearing destination
- **WHEN** the real modificar-producto flow receives `cambia las empanadas de verdura por empanadas carne picante` for an order containing four source empanadas and the destination exists in the commerce catalog
- **THEN** product recognition resolves the descriptor-bearing destination without a false presentation mismatch, allowing the existing omitted-quantity flow to transfer all four units

#### Scenario: Unknown replacement destination preserves source
- **WHEN** the real modificar-producto flow receives a replacement command whose destination is absent from the commerce catalog
- **THEN** recognition does not fabricate a destination match and the existing flow preserves the source order line unchanged
