## MODIFIED Requirements

### Requirement: Catalog item shape

The function SHALL accept `productos_presentaciones` as a list of dicts with the spec's shape: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`, and an optional caller-provided collection of applicable product aliases. A catalog item missing `producto_presentacion_id` is ignored. The fields `producto_id` and `presentacion_id` are required. The caller is responsible for converting database models to this shape and for projecting all active product-wide aliases plus only the active presentation-specific aliases for that exact row.

#### Scenario: Catalog item without id is ignored
- **WHEN** the test calls `detectar_productos("pizza", [{"producto_nombre": "Pizza"}, {"producto_presentacion_id": 1, "producto_nombre": "Pizza"}])`
- **THEN** the result reflects only the second item with an ID

#### Scenario: activo defaults to True when missing
- **WHEN** the test calls the function with a catalog item that does not have an `activo` field but has `disponible: True`
- **THEN** the item is treated as available

#### Scenario: presentacion_descripcion may be empty
- **WHEN** the test calls the function with a catalog item that has an empty `presentacion_descripcion`
- **THEN** the item is still recognized for presentation matching through `presentacion_codigo`

#### Scenario: Alias collection may be absent
- **WHEN** a catalog item contains no alias collection
- **THEN** canonical product and structured presentation matching continue normally without a hardcoded product-alias fallback

### Requirement: Product matching against producto_nombre

The function SHALL match the user text against each catalog item's `producto_nombre` and its caller-provided applicable product aliases using the existing fuzzy pipeline: text normalization, quantity words, stopwords, phonetic substitutions, prefix matching, segmentation, quantity extraction, and RapidFuzz scoring. Product aliases SHALL come from the supplied catalog rather than a hardcoded production alias map. Alias-source migration SHALL preserve existing thresholds, scores, candidate ranking, ambiguity, and result ordering for the migrated aliases.

#### Scenario: Unique product alias match
- **WHEN** the test calls `detectar_productos` with `"quiero una pizza muzza"` and an eligible pizza catalog row containing the applicable `muzza` alias
- **THEN** the result has the same recognized or possible product-presentation IDs, ranking, and ordering as the frozen pre-migration behavior

#### Scenario: Alias absent from supplied catalog does not match
- **WHEN** input contains an alias but no supplied catalog row exposes that alias or canonically matches the input
- **THEN** the alias does not introduce a recognized product

#### Scenario: Shared alias preserves ambiguity
- **WHEN** the same normalized alias is applicable to rows for different products in the supplied catalog
- **THEN** the recognizer returns the valid candidates according to existing fuzzy ambiguity and ordering rules rather than forcing one product

### Requirement: No additional implementation

The product recognizer SHALL remain a pure matching component and SHALL NOT introduce a router, FastAPI endpoint, persistence model, repository query, database session access, `print` statement, debug CLI behavior, semantic recognizer, or vector dependency. Product-alias persistence, querying, and seeding SHALL remain outside `backend.recognizers`; the recognizer receives applicable aliases through the caller-provided catalog.

#### Scenario: Recognizer has no database alias access
- **WHEN** the recognizer source and imports are inspected
- **THEN** it contains no SQLAlchemy, alias repository, alias service, or database session access

#### Scenario: Public compatibility entry point remains
- **WHEN** a caller imports `detectar_productos` or uses `FuzzyProductRecognizer`
- **THEN** both remain available with the frozen plain-dictionary result contract

### Requirement: Fuzzy recognizer conforms to the new abstraction

The existing `backend.recognizers.product_recognizer` implementation SHALL conform to `ProductRecognizerProtocol` through the protocol-compatible fuzzy implementation in `backend/recognizers/fuzzy_product_recognizer.py` without changing its matching algorithm, thresholds, normalization rules, candidate ranking, result fields, or result ordering. Product aliases SHALL be read from caller-provided catalog rows, and the former hardcoded product alias map SHALL not remain a production authority after migration.

#### Scenario: Existing fuzzy behavior remains unique

- **WHEN** an exact product/presentation or migrated alias match is evaluated against equivalent catalog data before and after persistence integration
- **THEN** the same `producto_presentacion_id` is the unique result with compatible scoring and ordering

#### Scenario: Existing fuzzy behavior remains ambiguous

- **WHEN** an ambiguous product or shared alias is evaluated against the same catalog scope
- **THEN** the same candidate IDs remain in the possible-match group with the same ordering

#### Scenario: Existing restricted refinement remains compatible

- **WHEN** a refinement such as `picante` or `grande` is evaluated against the same restricted pending-flow candidates
- **THEN** the same candidate is selected or the same ambiguity remains, and presentation extraction data is unchanged

## ADDED Requirements

### Requirement: Alias applicability is row-scoped

For each supplied catalog row, the recognizer SHALL consider every active general alias projected for its `producto_id` and only presentation-specific aliases projected for that exact `producto_presentacion_id`. A product-wide alias without a presentation token MAY preserve multiple presentation candidates; a presentation-specific alias SHALL resolve only its associated row.

#### Scenario: General alias can return multiple presentations
- **WHEN** `muzza` is supplied as a general alias for a product with multiple eligible presentations and input specifies no presentation
- **THEN** the recognizer preserves the current possible-candidate behavior for those presentations

#### Scenario: Presentation-specific alias selects one row
- **WHEN** a supplied alias belongs to exactly one `producto_presentacion_id`
- **THEN** that alias cannot match another presentation of the same product

### Requirement: Structured presentation matching remains independent

Structured presentation matching through `presentacion_codigo`, `presentacion_descripcion`, `PRESENTACION_ALIASES`, and `_extraer_presentacion` SHALL remain available and SHALL NOT depend on rows in `producto_aliases`.

#### Scenario: Ordinary presentation terms still resolve
- **WHEN** input uses `chica`, `grande`, `unidad`, `1 litro`, or another existing structured presentation expression
- **THEN** recognition continues through presentation fields and existing presentation normalization even when no persisted product alias has that value

### Requirement: PostgreSQL aliases preserve all recognition flows

After the caller catalog is enriched with persisted aliases, initial `agregar_producto`, pending product selection, `quitar_producto`, and `modificar_producto` source/destination recognition SHALL preserve their commerce, active-order-line, and restricted-candidate boundaries and the frozen result behavior.

#### Scenario: Commerce catalog excludes another commerce aliases
- **WHEN** initial or destination recognition runs for one commerce
- **THEN** aliases owned by products in another commerce cannot affect its result

#### Scenario: Pending selection remains restricted
- **WHEN** a pending selection is refined using candidate product-presentation IDs
- **THEN** only aliases applicable to those candidate IDs are exposed and no full-catalog candidate is introduced

#### Scenario: Subphase 4.1 baseline remains compatible
- **WHEN** contract and baseline cases for exact, alias, ambiguous, refinement, quantity, and unknown input run with persisted alias projection
- **THEN** result keys, IDs, grouping, quantities, ordering, availability handling, and accepted known limitations remain compatible
