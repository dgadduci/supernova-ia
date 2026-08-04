## ADDED Requirements

### Requirement: Explicit frozen recognizer types

The system SHALL define static aliases or `TypedDict` types in `backend/recognizers/product_recognizer_contract.py` for the current catalog and result dictionaries without changing runtime values. The documented catalog projection SHALL include `producto_presentacion_id: int`, `producto_id: int`, `presentacion_id: int`, `categoria_id: int`, `producto_nombre: str`, `categoria_nombre: str`, `presentacion_codigo: str`, `presentacion_descripcion: str`, `activo: bool`, and `disponible: bool`; additional caller-supplied fields SHALL remain permitted and preserved in matched output entries.

#### Scenario: Catalog projection types are available
- **WHEN** a consumer imports the contract types
- **THEN** it can type the required catalog fields and the recognized product fields without importing SQLAlchemy or runtime database models

#### Scenario: Runtime dictionaries remain ordinary dictionaries
- **WHEN** the fuzzy recognizer returns a result
- **THEN** the result remains a plain `dict` and no runtime model conversion is required

### Requirement: Exact four-key result contract

The system SHALL describe `ProductRecognizerResult` as a plain dictionary with exactly these top-level keys, in this insertion order: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, and `no_encontrados`. Each value SHALL be a list and SHALL never be `None`.

#### Scenario: Result key names and order are frozen
- **WHEN** a caller inspects a recognizer result
- **THEN** its key set and insertion order are exactly `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`

#### Scenario: Empty text preserves the segmentation fallback
- **WHEN** recognition receives empty text and an empty catalog
- **THEN** the three product collections are empty and `no_encontrados` contains exactly `{"texto_origen": ""}`

### Requirement: Nested result structures and preserved fields

The system SHALL describe `encontrados` and `encontrados_no_disponibles` as lists of recognized product dictionaries. Each recognized product SHALL preserve every field from its source catalog entry and add `cantidad: int` and `texto_origen: str`. The system SHALL describe `encontrados_posibles` as a list of groups shaped exactly as `{"texto_origen": str, "productos": list[RecognizedProduct]}` and `no_encontrados` as a list of `{"texto_origen": str}` entries.

#### Scenario: Found product preserves catalog fields
- **WHEN** a catalog item is recognized
- **THEN** every source catalog field remains in the output entry alongside an integer `cantidad` and string `texto_origen`

#### Scenario: Possible products are grouped
- **WHEN** one input segment matches multiple available presentations
- **THEN** one possible-match group contains the segment text and a `productos` list with the recognized product entries

#### Scenario: Unknown fragments use the unmatched shape
- **WHEN** an input segment matches no catalog item
- **THEN** `no_encontrados` contains exactly one dictionary for that segment with only `texto_origen`

### Requirement: Empty values, quantities, and ordering are stable

The fuzzy contract SHALL preserve these semantics: `cantidad` is a positive integer and defaults to `1`; empty catalogs produce no found, possible, or unavailable entries and retain unmatched input segments; unknown fragments retain segmentation order; found and unavailable entries are ordered by descending confidence with stable ties; possible groups retain first-seen segment order and products retain confidence order; duplicate product-presentation IDs retain only their strongest match. Entries filtered by false product, presentation, or product-presentation activity flags remain absent from all collections, while entries with `disponible` false are returned in `encontrados_no_disponibles`.

#### Scenario: Omitted quantity defaults to one
- **WHEN** a recognized segment contains no numeric or quantity word
- **THEN** its recognized product entry has `cantidad == 1`

#### Scenario: Explicit quantity is preserved
- **WHEN** a recognized segment contains an explicit integer, quantity word, or docena expression
- **THEN** its recognized product entry has the corresponding positive integer quantity

#### Scenario: Result ordering remains deterministic
- **WHEN** multiple segments or candidates are recognized
- **THEN** the output ordering follows segment order, descending confidence, stable ties, and strongest-match deduplication as defined above

### Requirement: Separate protocol surface

The system SHALL define `ProductRecognizerProtocol` in `backend/recognizers/product_recognizer_contract.py` with `recognize(text: str, catalog: list[dict]) -> ProductRecognizerResult`. The protocol module SHALL not import SQLAlchemy, HTTP, LLM, or repository modules, and SHALL remain separate from the concrete fuzzy implementation where practical.

#### Scenario: Protocol is importable without infrastructure
- **WHEN** a consumer imports `ProductRecognizerProtocol` and the contract types
- **THEN** the import succeeds without database, HTTP, LLM, or repository dependencies

#### Scenario: Protocol uses the frozen shape
- **WHEN** an implementation is checked against the protocol
- **THEN** it accepts the caller-provided catalog and returns the exact four-key result contract

### Requirement: Separate fuzzy implementation delegates unchanged behavior

The system SHALL provide `FuzzyProductRecognizer` in `backend/recognizers/fuzzy_product_recognizer.py` when practical. Its `recognize` method SHALL delegate to the existing `backend.recognizers.product_recognizer.detectar_productos` implementation without copying, reordering, normalizing, or otherwise transforming the result. If a separate module is not practical because of import-cycle or public-surface constraints, the implementation SHALL remain in the existing fuzzy module while preserving the same separation of protocol types and implementation behavior.

#### Scenario: Fuzzy adapter and legacy function agree
- **WHEN** the same text and catalog are passed to `FuzzyProductRecognizer().recognize` and `detectar_productos`
- **THEN** recognized IDs, candidate IDs, quantities, unknown fragments, unavailable entries, and collection ordering are identical

### Requirement: Legacy function compatibility

The system SHALL keep `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` available for existing consumers and SHALL preserve its current public import and plain-dictionary return behavior.

#### Scenario: Existing direct imports continue to work
- **WHEN** an existing backend module imports and calls `detectar_productos`
- **THEN** the import succeeds and the call returns the unchanged observable contract

### Requirement: Reusable contract test surface

The system SHALL provide reusable contract tests that accept a recognizer implementation and verify the frozen observable behavior without requiring SQLAlchemy, an HTTP server, an LLM, or production database state.

#### Scenario: Contract tests run against fuzzy recognition
- **WHEN** the contract test suite is configured with `FuzzyProductRecognizer`
- **THEN** it verifies exact, ambiguous, restricted refinement, unknown, alias, presentation, quantity, availability, field-preservation, and ordering cases

#### Scenario: Contract tests are implementation-neutral
- **WHEN** a future recognizer implementation is supplied with the same catalog fixture
- **THEN** the same test harness can execute without importing fuzzy-private helpers
