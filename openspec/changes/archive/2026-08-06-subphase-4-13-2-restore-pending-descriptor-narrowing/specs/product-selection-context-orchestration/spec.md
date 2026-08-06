## ADDED Requirements

### Requirement: Pending selection recognizes exact restricted descriptor codes without changing fuzzy aliases

When the real recognizer returns zero `encontrados` and no product-level
`encontrados_posibles`, `resolve_product_selection` SHALL preserve its normal
structured-presentation path based on `_extraer_presentacion(message)`. If no
structured alias is extracted, it SHALL additionally allow an exact normalized
reply word to match a whole word in a row's `producto_nombre` or
`presentacion_codigo` in the catalog already passed to the resolver.

This resolver-local fallback SHALL NOT add to `PRESENTACION_ALIASES`, alter
fuzzy recognition, or alter the existing branches that consume recognizer
results. It SHALL preserve ordered intersection with persisted
`active_intent.candidate_ids`: one ID resolves via the existing helper,
multiple IDs remain pending with the narrowed set, and no IDs returns the
active intent unchanged.

#### Scenario: Exact descriptor code resolves within pending candidates

- **WHEN** active candidate IDs represent `Empanada de Carne` with codes
  `PICANTE` and `TRADICIONAL`, and the reply is `carne picante`
- **THEN** the resolver selects only the `PICANTE` row, preserves quantity,
  completes the product requirement, and returns `ready`
- **AND** `picante` is not a presentation alias and does not affect fuzzy
  presentation filtering

#### Scenario: Product-name descriptor remains supported

- **WHEN** active candidates differ by the exact normalized whole word
  `picante` in `producto_nombre` and both use code `UNIDAD`
- **THEN** the reply `la picante` uniquely selects the Picante-named row

#### Scenario: Substring does not match descriptor code or name

- **WHEN** a candidate has code or name token `picantes`, but not the exact
  normalized token `picante`
- **AND** the reply is `picante`
- **THEN** that candidate is not selected by the fallback

#### Scenario: Candidate scope remains closed

- **WHEN** a matching name or code exists outside `active_intent.candidate_ids`
- **THEN** the resolver cannot select it
