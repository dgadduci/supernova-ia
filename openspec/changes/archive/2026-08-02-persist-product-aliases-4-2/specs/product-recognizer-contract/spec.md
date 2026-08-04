## MODIFIED Requirements

### Requirement: Explicit frozen recognizer types

The system SHALL define static aliases or `TypedDict` types in `backend/recognizers/product_recognizer_contract.py` for the current catalog and result dictionaries without changing runtime values. The documented catalog projection SHALL include `producto_presentacion_id: int`, `producto_id: int`, `presentacion_id: int`, `categoria_id: int`, `producto_nombre: str`, `categoria_nombre: str`, `presentacion_codigo: str`, `presentacion_descripcion: str`, `activo: bool`, `disponible: bool`, and an optional caller-provided collection of applicable normalized product aliases; additional caller-supplied fields SHALL remain permitted and preserved in matched output entries. Alias projection types SHALL remain infrastructure-free and SHALL distinguish product-wide applicability from aliases already filtered to one exact product-presentation without importing SQLAlchemy models.

#### Scenario: Catalog projection types are available

- **WHEN** a consumer imports the contract types
- **THEN** it can type the required catalog fields, applicable alias data, and recognized product fields without importing SQLAlchemy or runtime database models

#### Scenario: Runtime dictionaries remain ordinary dictionaries

- **WHEN** the fuzzy recognizer returns a result
- **THEN** the result remains a plain `dict` and no runtime model conversion is required

#### Scenario: Catalog without aliases remains valid

- **WHEN** a caller supplies a catalog entry without the optional alias collection
- **THEN** the protocol accepts the entry and recognition proceeds using canonical product and structured presentation fields

## ADDED Requirements

### Requirement: Alias data is caller-provided and persistence-independent

`ProductRecognizerProtocol` implementations SHALL consume applicable aliases only from the supplied catalog projection and SHALL NOT import SQLAlchemy, repositories, services, or database sessions to obtain aliases. The protocol's exact four-key result contract, preserved-field behavior, quantity semantics, and ordering SHALL remain unchanged when alias data is present.

#### Scenario: Protocol uses projected aliases without infrastructure
- **WHEN** a caller supplies a catalog containing applicable aliases and invokes a protocol implementation
- **THEN** alias recognition occurs without any database or repository access from the recognizer

#### Scenario: Alias fields are preserved in matched output
- **WHEN** a catalog row containing alias projection data is recognized
- **THEN** that caller-supplied data is preserved alongside the frozen recognized-product fields, `cantidad`, and `texto_origen`

### Requirement: Restricted catalogs remain authoritative

Applicable alias data SHALL NOT permit a recognizer implementation to introduce a product-presentation absent from the supplied catalog. Presentation-specific aliases SHALL be projected only onto their exact product-presentation before protocol invocation.

#### Scenario: Alias cannot broaden candidate scope
- **WHEN** an alias belongs to a product-presentation outside a restricted candidate catalog
- **THEN** recognition does not return that product-presentation

#### Scenario: Sibling presentation does not inherit a specific alias
- **WHEN** one catalog row has a presentation-specific alias and another row represents a sibling presentation of the same product
- **THEN** only the exact associated row receives and can match that alias
