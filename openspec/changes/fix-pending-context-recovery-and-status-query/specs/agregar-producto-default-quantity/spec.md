## ADDED Requirements

### Requirement: Omitted product-add quantity uses the declared default

When `process_agregar_producto` receives no `cantidad` from recognition, it
SHALL use the existing `agregar_producto` contract default `1` as completed
resolved data and as its completed quantity requirement. It SHALL preserve an
explicit recognized positive integer quantity unchanged. It SHALL not query a
catalog, consult an LLM or own transaction control.

#### Scenario: Ambiguous products without a quantity retain default one

- **WHEN** recognition returns two product-presentation candidate IDs and no
  quantity
- **THEN** the processed intent is pending only for presentation selection,
  contains `resolved_data.cantidad == 1`, and its quantity requirement is
  completed with value `1`

#### Scenario: Explicit quantity is preserved

- **WHEN** recognition supplies a positive integer quantity
- **THEN** the processed intent preserves that exact quantity rather than
  replacing it with the default
