# Capability: product-recognizer

## Purpose

Define the pure fuzzy product-matching module `backend.recognizers.product_recognizer` that takes free-text user input and a catalog of product-presentations and returns a structured dict with four keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`). The function receives the catalog as an argument (the caller is responsible for fetching from the DB and converting to the spec's input shape), does not query the database, does not depend on `backend.data.lista_json`, and does not call repositories.

## Requirements

### Requirement: detectar_productos function exists
The system SHALL export a single function `detectar_productos(texto: str, productos_presentaciones: list[dict]) -> dict` from `backend.recognizers.product_recognizer`. The function SHALL NOT depend on `backend.data.lista_json`, SHALL NOT query the database, SHALL NOT import repositories. The function is pure (plus a `rapidfuzz` import for fuzzy scoring).

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.recognizers.product_recognizer import detectar_productos`
- **THEN** the import completes without raising and the binding is a callable

#### Scenario: Function has no DB import
- **WHEN** the test greps the source for `from sqlalchemy` / `import sqlalchemy` / `from backend.db` / `import backend.repositories`
- **THEN** no match is found (the function does not touch the DB or repositories)

#### Scenario: Function has no lista_json import
- **WHEN** the test greps the source for `lista_json`
- **THEN** no match is found (the function does not depend on the legacy JSON file)

### Requirement: Function returns a Python dict with four keys
The function SHALL return a `dict` (NOT a JSON string) with exactly four keys: `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`. The function SHALL NOT call `json.dumps` on the result; it returns the dict directly.

#### Scenario: Result is a dict
- **WHEN** the test calls `detectar_productos` on any input
- **THEN** the return value is a Python `dict` (not a `str`)

#### Scenario: Result has exactly four keys
- **WHEN** the test inspects the keys of the result
- **THEN** the key set is exactly `{"encontrados", "encontrados_posibles", "encontrados_no_disponibles", "no_encontrados"}`

### Requirement: Catalog item shape
The function SHALL accept `productos_presentaciones` as a list of dicts with the spec's shape: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`, and an optional caller-provided collection of applicable product aliases. A catalog item missing `producto_presentacion_id` is ignored. The fields `producto_id` and `presentacion_id` are required. The caller is responsible for converting database models to this shape and for projecting all active product-wide aliases plus only the active presentation-specific aliases for that exact row.

#### Scenario: Catalog item without id is ignored
- **WHEN** the test calls `detectar_productos("pizza", [{"producto_nombre": "Pizza"}, {"producto_presentacion_id": 1, "producto_nombre": "Pizza"}])`
- **THEN** the result reflects only the second item (with id)

#### Scenario: activo defaults to True when missing
- **WHEN** the test calls the function with a catalog item that does NOT have an `activo` field but has `disponible: True`
- **THEN** the item is treated as available (the absence of `activo` is interpreted as `True`)

#### Scenario: presentacion_descripcion may be empty
- **WHEN** the test calls the function with a catalog item that has an empty `presentacion_descripcion` (matching the legacy data shape, where the equivalent was `tamanio` mapped to `presentacion_codigo`)
- **THEN** the item is still recognized for presentation matching; the match uses `presentacion_codigo`

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

#### Scenario: Unique product match
- **WHEN** the test calls `detectar_productos("quiero una pizza muzza", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza Mozzarella", "presentacion_codigo": "grande", "presentacion_descripcion": "Pizza grande de mozzarella", "activo": True, "disponible": True, "producto_id": 1, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas"}])`
- **THEN** the result has the product in `encontrados` (or `encontrados_posibles`), not in `no_encontrados` and not in `encontrados_no_disponibles`

### Requirement: Presentation matching against presentacion_codigo and presentacion_descripcion
The function SHALL match against the catalog item's `presentacion_codigo` and `presentacion_descripcion` after the product name match. A presentation-specific token in the user text restricts the match to that presentation.

#### Scenario: Explicit presentation resolves one candidate
- **WHEN** the test calls the function with a text containing a presentation token (e.g. "familiar") and a catalog with two presentations of the same product
- **THEN** only the presentation whose `presentacion_codigo` or `presentacion_descripcion` contains that token is in `encontrados`; the other is in `encontrados_posibles`

### Requirement: Unavailable handling
A product-presentation is unavailable when `activo is False` (when present; `True` by default if absent) or `disponible is False` (when present). Unavailable items are placed in `encontrados_no_disponibles`, not in `encontrados`.

#### Scenario: Unavailable product
- **WHEN** the test calls the function with a catalog item that has `activo: True` and `disponible: False`
- **THEN** the item is in `encontrados_no_disponibles`, not in `encontrados`

#### Scenario: Inactive product
- **WHEN** the test calls the function with a catalog item that has `activo: False` and `disponible: True`
- **THEN** the item is in `encontrados_no_disponibles`, not in `encontrados`

#### Scenario: activo field absent (defaults to True)
- **WHEN** the test calls the function with a catalog item that has NO `activo` field but has `disponible: True` (matching the legacy data shape)
- **THEN** the item is in `encontrados`, not in `encontrados_no_disponibles` (the absence of `activo` is interpreted as `True`)

#### Scenario: Legacy shape without activo is treated as available
- **WHEN** the test calls the function with a legacy-shape item (8 fields: id, idcategoria, nombre_producto, nombre_categoria, tamanio, precio, disponible) and `disponible: True`
- **THEN** the item is in `encontrados` (after the caller converts the legacy fields to the new shape with `producto_presentacion_id=id`, `producto_nombre=nombre_producto`, `presentacion_codigo=tamanio`, etc., and `activo` defaults to `True`)

### Requirement: Unknown products
A user text that matches no catalog item is placed in `no_encontrados` as the original text fragment.

#### Scenario: Unknown product
- **WHEN** the test calls `detectar_productos("quiero algo raro", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza", "presentacion_codigo": "grande", "presentacion_descripcion": "", "activo": True, "disponible": True, "producto_id": 1, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas"}])`
- **THEN** `no_encontrados` contains the unmatched fragment and `encontrados` is empty

### Requirement: Multiple products in one message
The function SHALL preserve the legacy behavior for multiple products in one message: each matched product appears in its own entry in `encontrados` with the correct `cantidad`.

#### Scenario: Multiple products and quantities
- **WHEN** the test calls the function with text "2 pizzas muzza y 1 empanada de carne" and a catalog with both products
- **THEN** both products are in `encontrados` with the correct `cantidad` values (2 and 1)

### Requirement: Restricted catalog
The function SHALL only consider catalog items in the supplied list. Items not in the list are ignored even if their name matches the user text.

#### Scenario: Restricted catalog
- **WHEN** the test calls the function with a text that matches a product name and a catalog that does NOT include that product
- **THEN** the product is NOT in `encontrados`; the user text fragment appears in `no_encontrados`

#### Scenario: Empty catalog returns empty
- **WHEN** the test calls the function with `productos_presentaciones=[]`
- **THEN** `encontrados` is `[]`, `encontrados_posibles` is `[]`, `encontrados_no_disponibles` is `[]`, and `no_encontrados` contains the unmatched fragment

### Requirement: Found products preserve catalog fields
Each entry in `encontrados` SHALL preserve every catalog field (`producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`) and add two fields: `cantidad` (int) and `texto_origen` (str). The legacy `precio` field is NOT in the input catalog (the caller drops it before passing data to the recognizer); the recognizer does not surface price in its output.

#### Scenario: Found product preserves all catalog fields
- **WHEN** the test calls the function with a text that matches a catalog item
- **THEN** the resulting `encontrados` entry has every original catalog field plus `cantidad` and `texto_origen`

#### Scenario: Found product has positive integer cantidad
- **WHEN** the test calls the function with "2 pizzas"
- **THEN** the resulting entry has `cantidad == 2` (an `int`)

#### Scenario: Found product has the matched fragment in texto_origen
- **WHEN** the test calls the function with text "pizza muzza"
- **THEN** the resulting entry's `texto_origen` contains the matched fragment

### Requirement: Possible products grouped
When one user-text segment matches multiple valid presentations of the same product, the function SHALL place them in ONE entry in `encontrados_posibles` with the shape `{"texto_origen": str, "productos": list[dict]}`.

#### Scenario: Same product with multiple presentations → one group
- **WHEN** the test calls the function with text "pizza" and a catalog with two presentations of the same product (e.g. `presentacion_codigo: "chica"` and `presentacion_codigo: "grande"`)
- **THEN** `encontrados_posibles` has exactly one group whose `productos` list contains both presentations

### Requirement: Module is importable without side effects
The system SHALL make `detectar_productos` importable from `backend.recognizers.product_recognizer` without side effects, errors, or required dependencies beyond the standard library, `rapidfuzz`, and the existing project modules.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.recognizers.product_recognizer import detectar_productos`
- **THEN** the import completes without raising and the binding is the function

### Requirement: No additional implementation
The product recognizer SHALL remain a pure matching component and SHALL NOT introduce a router, FastAPI endpoint, persistence model, repository query, database session access, `print` statement, debug CLI behavior, semantic recognizer, or vector dependency. Product-alias persistence, querying, and seeding SHALL remain outside `backend.recognizers`; the recognizer receives applicable aliases through the caller-provided catalog.

#### Scenario: Recognizer has no database alias access
- **WHEN** the recognizer source and imports are inspected
- **THEN** it contains no SQLAlchemy, alias repository, alias service, or database session access

#### Scenario: Public compatibility entry point remains
- **WHEN** a caller imports `detectar_productos` or uses `FuzzyProductRecognizer`
- **THEN** both remain available with the frozen plain-dictionary result contract

#### Scenario: Only the recognizer module is added
- **WHEN** the test lists Python files under `backend/recognizers/`
- **THEN** the file set is exactly `{"__init__.py", "product_recognizer.py"}`

#### Scenario: Only the one public symbol is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"detectar_productos"}`

### Requirement: Imperative removal and action verbs are stopwords
`backend.recognizers.product_recognizer.detectar_productos` SHALL treat imperative forms and infinitives of the removal, generic action, and add verbs (`quita`, `quitar`, `saca`, `sacame`, `sacala`, `quitala`, `quitalas`, `quitale`, `sacasela`, `elimina`, `eliminar`, `remueve`, `remover`, `borra`, `borrar`, `suprime`, `suprimir`, `agrega`, `agregar`) as stopwords. These tokens SHALL NOT participate in the token-based filter that drops candidates whose `producto_nombre` does not contain every significant user token.

#### Scenario: Quitar without quantity resolves the candidate
- **WHEN** the test calls `detectar_productos("quita las empanadas de pollo", [{"producto_presentacion_id": 1, "producto_nombre": "Empanada de Pollo", "presentacion_codigo": "unidad", "presentacion_descripcion": "Unidad", "activo": True, "disponible": True, "producto_id": 1, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Empanadas"}])`
- **THEN** the product is present in `encontrados` and `no_encontrados` does not contain the fragment

#### Scenario: Sacar in any conjugation form resolves the candidate
- **WHEN** the test calls `detectar_productos("sacame las empanadas de pollo", [...same catalog as above...])`
- **THEN** the product is present in `encontrados`

#### Scenario: Sacar pronominal conjugation resolves the candidate
- **WHEN** the test calls `detectar_productos("sacala empanadas de pollo", [...same catalog as above...])`
- **THEN** the product is present in `encontrados`

#### Scenario: Generic action verb resolves the candidate
- **WHEN** the test calls `detectar_productos("elimina la pizza muzza", [{"producto_presentacion_id": 2, "producto_nombre": "Pizza Mozzarella", "presentacion_codigo": "grande", "presentacion_descripcion": "Pizza grande de mozzarella", "activo": True, "disponible": True, "producto_id": 2, "presentacion_id": 2, "categoria_id": 2, "categoria_nombre": "Pizzas"}])`
- **THEN** the product is present in `encontrados`

#### Scenario: agregar_producto without explicit quantity resolves the candidate
- **WHEN** the test calls `detectar_productos("agrega empanadas de pollo", [...same empanada catalog as above...])`
- **THEN** the product is present in `encontrados`

#### Scenario: Stopword set includes the new imperative verbs
- **WHEN** the test imports `STOPWORDS` from `backend.recognizers.product_recognizer`
- **THEN** every token in the list `["quita", "quitar", "saca", "sacame", "sacala", "quitala", "quitalas", "quitale", "sacasela", "elimina", "eliminar", "remueve", "remover", "borra", "borrar", "suprime", "suprimir", "agrega", "agregar"]` is a member of the set

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