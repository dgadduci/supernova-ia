## ADDED Requirements

### Requirement: Fuzzy recognizer conforms to the new abstraction

The existing `backend.recognizers.product_recognizer` implementation SHALL conform to `ProductRecognizerProtocol` through a protocol-compatible fuzzy implementation, preferably in `backend/recognizers/fuzzy_product_recognizer.py`, without changing its matching algorithm, thresholds, normalization rules, aliases, candidate ranking, result fields, or result ordering.

#### Scenario: Existing fuzzy behavior remains unique
- **WHEN** an exact product and presentation match is evaluated before and after the abstraction is introduced
- **THEN** the same `producto_presentacion_id` is the unique result

#### Scenario: Existing fuzzy behavior remains ambiguous
- **WHEN** an ambiguous product such as `empanada de carne` or `pizza` is evaluated against the same catalog
- **THEN** the same candidate IDs remain in the possible-match group with the same ordering

#### Scenario: Existing restricted refinement remains compatible
- **WHEN** a refinement such as `picante` or `grande` is evaluated against the same restricted pending-flow candidates
- **THEN** the same candidate is selected or the same ambiguity remains

### Requirement: Complete backend recognizer consumers retain their contracts

All production result consumers and lifecycle paths across `backend/` SHALL continue receiving the current recognizer result shape and identifiers after practical composition boundaries adopt the abstraction. This includes initial `agregar_producto`, pending product selection, `quitar_producto`, `modificar_producto` source and destination recognition, product-intent resolution, pending-context dispatch, ready execution, and FIFO queued-intent promotion.

#### Scenario: Initial agregar producto remains compatible
- **WHEN** an existing `agregar_producto` recognition flow runs through the abstraction
- **THEN** its unique or pending result preserves the current product ID, candidate IDs, quantity, result keys, and status behavior

#### Scenario: Pending product selection remains compatible
- **WHEN** an active pending product-selection intent is refined through the abstraction using its restricted catalog
- **THEN** the resolver and dispatcher receive the same recognized IDs and produce the same ready or pending outcome

#### Scenario: Removal and modification remain compatible
- **WHEN** `quitar_producto` or either source/destination recognition stage of `modificar_producto` runs through the abstraction
- **THEN** the current order-line and commerce-catalog boundaries and recognized identifiers are preserved

#### Scenario: Queue promotion remains compatible
- **WHEN** a ready pending result is executed and the FIFO queue promotes the next intent
- **THEN** the promoted intent and its candidate state remain unchanged by the recognizer abstraction
