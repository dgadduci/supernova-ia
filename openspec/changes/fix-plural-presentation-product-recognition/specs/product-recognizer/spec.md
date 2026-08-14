## ADDED Requirements

### Requirement: Recognizer preserves approved plural presentation sizes

The shared product-text normalization SHALL map `grandes` to `grande` and
`chicas` to `chica` before generic singularization. It SHALL preserve the
existing normalization of quantity words and product plurals, so a message
such as `quiero dos napolitanas grandes` yields the product token
`napolitana`, presentation `grande`, and quantity `2`.

It SHALL NOT add a generic morphology rule, catalog fallback, fuzzy threshold
change, semantic/LLM authority or candidate outside the existing catalog.

#### Scenario: Plural Grande adds the exact quantity

- **WHEN** the current commerce catalog contains Napolitana Grande
- **AND WHEN** the customer says `quiero dos napolitanas grandes`
- **THEN** recognition returns only Napolitana Grande with quantity `2`
- **AND THEN** the existing add execution may increment its existing order
  line through the caller-owned transaction path.

#### Scenario: Plural Chica stays presentation-specific

- **WHEN** the catalog contains both Chica and Grande for a product
- **AND WHEN** the customer requests its product with `chicas`
- **THEN** recognition retains only Chica
- **AND THEN** it does not broaden candidates to another presentation.
