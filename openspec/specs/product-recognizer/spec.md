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

### Requirement: Presentation aliases exclude product descriptors

`PRESENTACION_ALIASES` SHALL contain only terms that represent a structured catalog presentation for the current recognition path. A product descriptor that occurs in `producto_nombre` but is not a catalog presentation SHALL NOT activate presentation filtering. In particular, `picante` SHALL NOT be a key in `PRESENTACION_ALIASES`; recognizing `empanadas carne picante` against an active `Empanada de Carne Picante` with presentation `unidad` SHALL retain that candidate through the normal fuzzy path.

#### Scenario: Product descriptor does not filter its own candidate

- **WHEN** the catalog contains `Empanada de Carne Picante` with `presentacion_codigo == "unidad"`
- **AND** the customer text is `empanadas carne picante`
- **THEN** the recognizer retains the unit candidate
- **AND** `picante` is not treated as a presentation alias

#### Scenario: Legitimate presentation aliases remain active

- **WHEN** the input includes an existing legitimate presentation term such as `grande`, `chica`, or `lata`
- **THEN** existing presentation filtering behavior is unchanged

### Requirement: Unavailable handling

The recognizer SHALL treat a product-presentation as unavailable when `activo is False` (when present; `True` by default if absent) or `disponible is False` (when present), and SHALL place unavailable items in `encontrados_no_disponibles`, not in `encontrados`.

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

The recognizer SHALL place user text that matches no catalog item in `no_encontrados` as the original text fragment.

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

The integration boundary at
`backend/intents/orchestration/agregar_producto_orchestrator.py`
SHALL resolve the recognizer through a settings-driven factory
exposed as
`backend.services.product_recognition_factory.get_product_recognizer(settings)`.
The factory SHALL return a `FuzzyProductRecognizer` when
`settings.product_recognizer_mode == "fuzzy"` and a
`ShadowedProductRecognizer` (decorating a `FuzzyProductRecognizer`)
when `settings.product_recognizer_mode == "shadow"`. The factory
SHALL be invoked once at orchestrator module import time with
`load_settings()`; the resulting recognizer is bound to the
module-level `_product_recognizer` symbol and re-exported as
`detectar_productos = _product_recognizer.recognize`. In both
modes the recognizer result observed by the listed consumers
SHALL be byte-for-byte equivalent to the fuzzy recognizer output.
The orchestrator module SHALL continue to expose
`detectar_productos` as the shared product-recognition boundary
used by `agregar_producto`, `quitar_producto`, and
`modificar_producto` orchestrators; the handlers and the intent
interpreter SHALL NOT be rewritten to consume a different
recognizer surface.

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

#### Scenario: Fuzzy mode returns the exact fuzzy result

- **WHEN** `product_recognizer_mode == "fuzzy"` and the
  `agregar_producto` orchestrator invokes `detectar_productos`
- **THEN** the shared boundary invokes the `FuzzyProductRecognizer`
  directly
- **AND** the returned `ProductRecognizerResult` is byte-for-byte
  equivalent to the output of
  `backend.recognizers.product_recognizer.detectar_productos`
- **AND** no shadow service, embedding client, or vector search
  service is invoked

#### Scenario: Shadow mode returns the exact fuzzy result

- **WHEN** `product_recognizer_mode == "shadow"` and the
  `agregar_producto` orchestrator invokes `detectar_productos`
- **THEN** the shared boundary invokes a `ShadowedProductRecognizer`
  that wraps the `FuzzyProductRecognizer`
- **AND** the `FuzzyProductRecognizer.recognize` method is invoked
  **exactly once** per call
- **AND** the `ShadowedProductRecognizer` forwards the
  already-computed fuzzy result and the measured fuzzy latency to
  the shadow service
- **AND** the shadow service does NOT invoke the fuzzy recognizer
- **AND** the returned `ProductRecognizerResult` is byte-for-byte
  equivalent to the underlying fuzzy recognizer output
- **AND** the `agregar_producto` orchestrator receives the same
  product ID, candidate IDs, quantity, and result keys as in
  fuzzy mode

#### Scenario: Shadow mode does not rewrite handlers

- **WHEN** the `agregar_producto`, `quitar_producto`, and
  `modificar_producto` orchestrators are inspected
- **THEN** they continue to import `detectar_productos` from
  `backend.intents.orchestration.agregar_producto_orchestrator`
- **AND** no handler, resolver, or intent-orchestration module
  imports the shadow service, the shadowed recognizer, the
  factory, the recorder, or the embedding client directly

#### Scenario: Orchestrator binding uses the settings-driven factory

- **WHEN** the orchestrator module is imported
- **THEN** `_product_recognizer` is the result of
  `get_product_recognizer(load_settings())`
- **AND** `detectar_productos = _product_recognizer.recognize` is
  re-exported from the orchestrator module

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

### Requirement: Fuzzy recognizer receives the full runtime-compatible commerce catalog for database-backed calibration cases

When the fuzzy product recognizer is invoked against a `catalog_scope: "commerce_dynamic_database"` calibration case, the caller MUST hand the recognizer the **full runtime-compatible commerce catalog** for the case's `id_comercio` — every commerce-scoped `producto_presentacion` entry that the real runtime catalog assembly would provide, including entries whose availability flags are `false` — exactly as the runtime call sites (`backend/intents/context/product_selection_context_resolver.py:165` and the matching paths in `product_modification_resolver.py`, `quitar_producto_recognizer.py`, `modificar_producto_recognizer.py`, and the manual loader at `backend/tests/manual_product_recognizer.py::_load_catalog`) hand the recognizer the runtime catalog.

The catalog MUST include every commerce-scoped `producto_presentacion` row for `id_comercio` returned by the real runtime catalog assembly, regardless of any expected-case field. No inactive or unavailable entry may be filtered out before recognition. The catalog entry shape MUST be the documented runtime field set:

- `producto_presentacion_id` (int);
- `producto_id` (int);
- `presentacion_id` (int);
- `categoria_id` (int);
- `producto_nombre` (str);
- `categoria_nombre` (str);
- `presentacion_codigo` (str);
- `presentacion_descripcion` (str);
- `activo` (bool);
- `producto_activo` (bool);
- `presentacion_activo` (bool);
- `disponible` (bool).

Entries MUST be sorted by `producto_presentacion_id` ascending. Inactive and unavailable entries (where any of `activo`, `producto_activo`, `presentacion_activo`, `disponible` is `false`) MUST remain present in the catalog with their original flags preserved exactly and MUST be classified by the recognizer's existing `disponibles` / `encontrados_no_disponibles` split (`backend/recognizers/product_recognizer.py:543-561`): available matches remain in `disponibles`; unavailable or inactive matches remain in `encontrados_no_disponibles`.

No expected-case field MAY influence catalog construction. Specifically, `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_decision`, `expected_producto_presentacion_id`, `expected_producto_presentacion_id_ref`, and any other label MUST NOT be consulted when the catalog is built. The catalog is determined solely by `id_comercio` and the current PostgreSQL state (loaded fresh from the database at calibration time, never read from the persisted `commerce_catalog_inventory`).

The fuzzy recognizer contract documented under the existing `### Requirement: Fuzzy baseline product recognition`, `### Requirement: Product name normalization`, and any other fuzzy requirement is preserved verbatim; this requirement governs the catalog assembly performed by the calibration caller, not the recognizer implementation.

#### Scenario: Catalog contains every commerce-scoped producto_presentacion entry returned by the real runtime catalog assembly

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case whose `id_comercio == 1` and whose fresh DB load returns every commerce-scoped `producto_presentacion` entry returned by the real runtime catalog assembly (active and inactive alike, with all four runtime flags preserved)
- **THEN** the fuzzy recognizer is invoked with a catalog that contains exactly those entries
- **AND** the entries are sorted by `producto_presentacion_id` ascending
- **AND** every entry carries the documented field set with its original availability flags
- **AND** the catalog handed to the recognizer is the fresh DB catalog — not the persisted `commerce_catalog_inventory`, even when both contain the same entries

#### Scenario: Catalog does not narrow on allowed_candidate_ids

- **WHEN** a case has `allowed_candidate_ids = [1, 9, 39]` but the fresh DB catalog for `id_comercio == 1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains all 80 entries
- **AND** entries for ids `1`, `9`, `39` are not specially marked, sorted differently, or removed
- **AND** `allowed_candidate_ids` is used only by the evaluator after recognition

#### Scenario: Catalog does not narrow on expected_producto_presentacion_id

- **WHEN** a case has `expected_producto_presentacion_id = 33` but the fresh DB catalog for `id_comercio == 1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains all 80 entries
- **AND** the entry for id `33` is not specially marked, scored differently, or removed

#### Scenario: Restricted candidates remain present in the catalog

- **WHEN** a case has `restricted_candidate_ids = [9]` and the fresh DB catalog for `id_comercio == 1` contains entries for ids `[1, 9, 39, ...]`
- **THEN** the catalog handed to the recognizer contains the entry for id `9`
- **AND** the evaluator flags id `9` as a boundary violation only if the recognizer returns it as a candidate
- **AND** no pre-recognition removal of id `9` happens

#### Scenario: Entries from another commerce are absent

- **WHEN** a case has `id_comercio == 1` and the fresh DB catalog for commerce `1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains only entries from commerce `1`
- **AND** no entry from commerce `2` (or any other commerce) is present

#### Scenario: Inactive and unavailable entries are present with their original flags and classified by the recognizer

- **WHEN** the fresh DB catalog for `id_comercio == 1` contains an entry with `producto_activo == false`, `activo == false`, `presentacion_activo == false`, or `disponible == false`
- **THEN** the catalog handed to the recognizer contains that entry
- **AND** the entry's four runtime availability flags (`activo`, `producto_activo`, `presentacion_activo`, `disponible`) are preserved exactly
- **AND** the recognizer classifies it under `encontrados_no_disponibles` (or equivalent unavailable surface) per the existing `disponibles` / `encontrados_no_disponibles` split
- **AND** matching available entries still appear in `disponibles`
- **AND** no inactive entry is silently removed before recognition

#### Scenario: Competing product outside allowed_candidate_ids is present and reachable

- **WHEN** the fresh DB catalog for `id_comercio == 1` contains an entry whose `producto_nombre` is a strong fuzzy match for the case's input text and whose `producto_presentacion_id` is NOT in the case's `allowed_candidate_ids`
- **THEN** the catalog handed to the recognizer contains that entry
- **AND** the recognizer MAY return it as a candidate
- **AND** the evaluator flags it as a boundary violation (or out-of-allowed) at evaluation time, not at catalog construction time

#### Scenario: 11 preserved in-memory cases continue to use embedded catalogs

- **WHEN** the runner evaluates a `catalog_scope: "in_memory"` case (one of the 11 preserved Subphase 4.11 cases)
- **THEN** the full-commerce catalog path is not used
- **AND** the case's embedded `catalogs[*].entries` is passed to the fuzzy recognizer unchanged
- **AND** the existing Subphase 4.11 fuzzy decision semantics are preserved

### Requirement: typed-discriminated-union contract for `encontrados_posibles`

The `ProductRecognizerResult` typed contract at `backend/recognizers/product_recognizer_contract.py` SHALL formally type `encontrados_posibles` as a backward-compatible discriminated union containing exactly two variants:

1. the **product-level ambiguity group** — the existing `PossibleMatchGroup` (`texto_origen: str`, `productos: list[RecognizedProduct]`), preserved byte-identically (no `kind` field is added to this variant); and
2. the **category-level ambiguity group** — a new `CategoryAmbiguityGroup(TypedDict, total=True)` with the explicit discriminator `kind: Literal["category"]`, plus `categoria_nombre: str` and `texto_origen: str`. The group carries NO `productos` field and exposes NO product ids.

The `ProductRecognizerResult.encontrados_posibles` element type SHALL widen from `list[PossibleMatchGroup]` to `list[PossibleMatchGroup | CategoryAmbiguityGroup]`. The four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`) are preserved unchanged. The `ProductRecognizerProtocol.recognize` signature is preserved unchanged. The `FuzzyProductRecognizer.recognize` adapter at `backend/recognizers/fuzzy_product_recognizer.py` continues to delegate to `detectar_productos` and to return the same `ProductRecognizerResult` shape (now widened through the union). The discriminable union is the contract; every consumer MUST branch on `group.get("kind") == "category"` (or equivalently `"kind" in group`) BEFORE accessing `productos`. The new typed contract is exported via `__all__`.

The widening is strictly backward-compatible: existing callers that operate only on the product-level variant continue to receive the existing shape (no `kind` field is added to the product-level variant). New callers that operate on the category-level variant must branch on the `kind: "category"` discriminator before accessing any field beyond the documented category-level shape.

#### Scenario: existing product-level variant shape is byte-identical

- **WHEN** the test calls `detectar_productos` with any input that produces a product-level candidate via `_extraer_candidatos` (e.g., `"pizza muzzarella"` against a catalog containing `Pizza de Muzzarella`)
- **THEN** the resulting `encontrados_posibles` entry carries exactly the fields `texto_origen` (str) and `productos` (list of dicts with the catalog fields plus `cantidad` and `texto_origen`)
- **AND** the entry does NOT carry a `kind` field
- **AND** the entry shape is byte-identical to the pre-Subphase-4.11.5 result for the same input

#### Scenario: category-level variant carries the explicit discriminator

- **WHEN** the test calls `detectar_productos("un postre", [...Postres entries...])` and the existing fuzzy pipeline produced no product-level candidate
- **THEN** the resulting `encontrados_posibles` entry carries exactly the fields `kind: "category"`, `categoria_nombre` (str), and `texto_origen` (str)
- **AND** the entry does NOT carry a `productos` list
- **AND** the discriminator check `group.get("kind") == "category"` returns `True` for the category-level entry and `False` for the product-level entry

#### Scenario: ProductRecognizerResult formally types both variants

- **WHEN** the test imports `ProductRecognizerResult`, `PossibleMatchGroup`, and `CategoryAmbiguityGroup` from `backend.recognizers.product_recognizer_contract`
- **AND** the test imports `CategoryAmbiguityGroup` as a `TypedDict` subclass
- **THEN** the type relationships resolve cleanly under `mypy --strict`
- **AND** `ProductRecognizerResult["encontrados_posibles"]` is typed as a list whose elements type-check as either `PossibleMatchGroup` or `CategoryAmbiguityGroup`
- **AND** the `ProductRecognizerProtocol.recognize` return type is `ProductRecognizerResult` (preserved unchanged)

#### Scenario: every production reader handles both variants

- **WHEN** the test inspects every production reader of `encontrados_posibles` documented in the Subphase 4.11.5 proposal (the calibration runner, the shadow service, the `agregar_producto` resolver, the `quitar_producto` recognizer and orchestrator, the `modificar_producto` recognizer and resolver, the product-selection context resolver, the order-line selection resolver, and the product modification resolver)
- **THEN** every reader branches on `group.get("kind") == "category"` BEFORE accessing `productos`
- **AND** every reader skips category-level groups safely (no candidate ids are extracted; no `KeyError` is raised)
- **AND** no unchecked `grupo["productos"]` access remains in any execution path where a category group can arrive (verified by a per-reader grep / static assertion)

#### Scenario: no unsafe direct access to `grupo["productos"]` remains

- **WHEN** the test greps the source of each adapted production reader for the literal pattern `group["productos"]` (direct dict access)
- **THEN** every occurrence is either (a) guarded by a preceding `group.get("kind") == "category"` check that `continue`s / `return`s, or (b) inside a test file (not in production code)
- **AND** no production reader does `grupo["productos"]` access without a discriminator check

### Requirement: muzarrella alias closes the residual fuzzy-misspelling gap

The document-level `ALIASES_PALABRAS` map at `backend/recognizers/product_recognizer.py:53-68` SHALL include the entry `"muzarrella": "mozzarella"`. The entry is read by the existing `_aplicar_aliases` helper (`backend/recognizers/product_recognizer.py:166-168`) during the `_normalizar_palabras_pedido` tokenization at `backend/recognizers/product_recognizer.py:170-178` and reaches the existing `_extraer_candidatos` pipeline through the same path as every other entry. The runtime alias authority (the catalog-projected aliases carried by `_row_aliases` at `backend/recognizers/product_recognizer.py:71-80`) and the Subphase 4.2 PostgreSQL alias persistence surface are unchanged. The 11 existing alias entries (including the 10 other mozzarella variants) are preserved verbatim; the new entry is added between `"mozarella"` and `"muzzarela"` to keep the mozzarella variants visually grouped.

#### Scenario: muzarrella closes the residual c1-fuzzy-vector-disagreement-muzarrella case

- **WHEN** the calibration runner evaluates the case `c1-fuzzy-vector-disagreement-muzarrella` (input `"muzarrella"`, `id_comercio: 1`, `expected_decision: unique`, `allowed_candidate_ids: [1, 2]`, expected `producto_presentacion_id: 1`)
- **THEN** the fuzzy recognizer normalizes `"muzarrella"` via `_normalizar_palabras_pedido` to the singular form
- **AND** `_aplicar_aliases` rewrites the token to `"mozzarella"` through the new `ALIASES_PALABRAS` entry
- **AND** the fuzzy matches the rewritten token against the catalog entries `pid=1` (`Pizza de Muzzarella GRANDE`) and `pid=2` (`Pizza de Muzzarella CHICA`) via the existing `_extraer_candidatos` and `_filtrar_por_tokens_clave` pipeline
- **AND** the case is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: existing alias entries are preserved

- **WHEN** the test imports `ALIASES_PALABRAS` from `backend.recognizers.product_recognizer`
- **THEN** every entry in the list `["muza", "muzza", "muzarela", "muzarella", "mozarela", "mozarella", "muzzarela", "muzzarella", "musarela", "musarella", "fugazeta", "fugazetta", "napoli", "calabreza"]` is a member of the map
- **AND** every entry maps to the documented canonical form (`"mozzarella"`, `"fugazzeta"`, `"napolitana"`, `"calabresa"`)

#### Scenario: new entry is reachable through the same path as the existing entries

- **WHEN** the test calls `detectar_productos("muzarrella", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 1, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}])`
- **THEN** the result contains the entry in `encontrados` (or `encontrados_posibles`), not in `no_encontrados` and not in `encontrados_no_disponibles`
- **AND** the result shape, the per-entry fields, and the `cantidad` / `texto_origen` discipline are identical to the result the existing `"muzza"` alias entry produces

#### Scenario: new entry is documented as a static alias

- **WHEN** the test inspects the source of `ALIASES_PALABRAS`
- **THEN** the entry `"muzarrella": "mozzarella"` is a frozen constant in the module-level map
- **AND** the entry is not duplicated at runtime, not read from the database, not read from the catalog, and not read from any environment variable
- **AND** the runtime alias authority for production recognition continues to be the catalog-projected aliases carried by `_row_aliases`

### Requirement: category-scope matching signals category-level ambiguity through the typed-discriminated-union `encontrados_posibles` flow

The `detectar_productos` function SHALL include a category-scope matching pass that runs after `_extraer_candidatos` (at `backend/recognizers/product_recognizer.py:402-498`) and `_filtrar_por_tokens_clave` (at `backend/recognizers/product_recognizer.py:340-364`) and signals category-level ambiguity through the typed-discriminated-union `encontrados_posibles` flow without exposing every entry in the matched category as an ordinary product candidate. The pass builds a per-call index of the catalog's `categoria_nombre` values (lowercased and singularized via the existing `_singularizar_simple` helper at `backend/recognizers/product_recognizer.py:156-163`) and matches each significant user token from `texto_segmento` (after the existing `tokens_significativos` filter at `backend/recognizers/product_recognizer.py:343-350` that excludes `STOPWORDS`, `TAMANIOS`, `PALABRAS_CANTIDAD`, digits, and tokens shorter than 3 characters) against the index. When a significant user token matches a catalog `categoria_nombre`, the pass appends a `CategoryAmbiguityGroup` to `encontrados_posibles` carrying `kind: "category"`, `categoria_nombre` (the normalized category name), and `texto_origen` (the original segment) — the group does NOT carry a `productos` list and the matched catalog entries are NOT exposed as ordinary product candidates.

The pass is purely additive: it never removes a candidate that the existing fuzzy pipeline already produced, it never bypasses the existing `_extraer_candidatos` / `_filtrar_por_tokens_clave` / `_extraer_presentacion` / `_calcular_score` discipline, it never bypasses the `STOPWORDS` / `TAMANIOS` / `PALABRAS_CANTIDAD` filter, it never bypasses the four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`), and it never adds a product candidate via the category-level signal. The pass runs only when the existing fuzzy pipeline produced no product candidate for the segment; when the existing pipeline produced at least one candidate, the pass is skipped (the existing behavior is preserved). The pass is deterministic (no randomness, no clock, no environment variable, no module-level state). The recognizer SHALL NOT consult `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label — the recognizer signature and the recognizer's responsibility are unchanged.

The `encontrados_posibles` element type is the typed-discriminated-union `list[PossibleMatchGroup | CategoryAmbiguityGroup]` documented under the `### Requirement: typed-discriminated-union contract for encontrados_posibles` requirement. The matched catalog entries are NOT exposed as evaluable product candidates and are NOT routed through the `encontrados` / `encontrados_posibles[].productos[]` / `encontrados_no_disponibles` split — the runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`).

#### Scenario: "un postre" produces category-level ambiguity without promoting the full category as evaluable product candidates

- **WHEN** the test calls `detectar_productos("un postre", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}, ...])` against the Subphase 4.11.4 `commerce_catalog_inventory["1"]` `Postres` entries (pids 69, 70, 71, 72)
- **THEN** `encontrados` is empty (the existing fuzzy pipeline produced no product candidate for the segment)
- **AND** `encontrados_posibles` contains exactly one category-level group with `kind: "category"`, `categoria_nombre: "Postres"`, and `texto_origen: "un postre"`
- **AND** the category-level group does NOT carry a `productos` list — the 4 `Postres` product ids are NOT exposed as evaluable product candidates and are NOT routed through the `encontrados` / `encontrados_posibles[].productos[]` / `encontrados_no_disponibles` split
- **AND** the calibration case `c1-ambiguous-postre` (input `"un postre"`, `expected_decision: ambiguous`, `allowed_candidate_ids: [69, 70, 71, 72]`) is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: "otra pizza" produces category-level ambiguity without candidate-boundary violations

- **WHEN** the test calls `detectar_productos("otra pizza", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 771, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}, ...])` against the Subphase 4.11.4 `commerce_catalog_inventory["1"]` `Pizzas` entries (30 entries)
- **THEN** `encontrados` is empty
- **AND** `encontrados_posibles` contains exactly one category-level group with `kind: "category"`, `categoria_nombre: "Pizzas"`, and `texto_origen: "otra pizza"`
- **AND** the category-level group does NOT carry a `productos` list — the 30 `Pizzas` product ids are NOT exposed as evaluable product candidates
- **AND** the runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire when processing this case against `allowed_candidate_ids: [1, 2, 3, 4]` because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`)
- **AND** the calibration case `c1-ambiguous-pizza-again` (input `"otra pizza"`, `expected_decision: ambiguous`, `allowed_candidate_ids: [1, 2, 3, 4]`) is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: no allowed_candidate_ids leakage exists

- **WHEN** the test inspects `backend.recognizers.product_recognizer`
- **THEN** `inspect.signature(detectar_productos)` is unchanged (parameters: `texto: str`, `productos_presentaciones: list[dict]`)
- **AND** the module does NOT import anything named `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label
- **AND** the `_coincidencia_categoria` helper signature is `(texto_segmento: str, catalogo: list[dict]) -> str | None` and does NOT accept or expose any calibration label
- **AND** the recognizer signature and the recognizer's responsibility are unchanged

#### Scenario: ordinary product-level matches are byte-identical to the pre-4.11.5 result

- **WHEN** the test calls `detectar_productos("pizza muzzarella", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 771, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}, {"producto_presentacion_id": 2, "producto_nombre": "Pizza Napolitana", "producto_id": 772, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande napolitana", "activo": True, "disponible": True}])`
- **THEN** the result contains `pid=1` in `encontrados` (the existing fuzzy pipeline matched the input against `producto_nombre`)
- **AND** the category pass does NOT add a category-level group to `encontrados_posibles` because the existing pipeline already produced a candidate for the segment
- **AND** the result is byte-identical to the pre-Subphase-4.11.5 result for this input (the existing product-level `encontrados_posibles` shape is preserved — no `kind` field is added)

#### Scenario: category pass is purely additive

- **WHEN** the existing fuzzy pipeline produced at least one product candidate for the segment
- **THEN** the category pass does NOT run (the existing fuzzy pipeline result is preserved verbatim)
- **AND** the category pass does NOT add a category-level group to `encontrados_posibles`
- **AND** the category pass does NOT remove any pre-existing product candidate

#### Scenario: category pass respects the stopword / size / digit / quantity-word filter

- **WHEN** the test calls `detectar_productos("un grande postre", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}])`
- **THEN** the tokens `un`, `grande`, `postre` are computed via the existing `tokens_significativos` filter
- **AND** `un` is excluded (PALABRAS_CANTIDAD)
- **AND** `grande` is excluded (TAMANIOS)
- **AND** `postre` is the only significant token
- **AND** the category pass matches `postre` against the catalog's `Postres` category
- **AND** the result contains a category-level `encontrados_posibles` group with `kind: "category"` and `categoria_nombre: "Postres"`

#### Scenario: category pass does not run when the input reduces to no significant tokens

- **WHEN** the test calls `detectar_productos("un de con", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}])`
- **THEN** the tokens `un`, `de`, `con` are all excluded by the `tokens_significativos` filter
- **AND** the category pass has no significant tokens to match
- **AND** the result is `no_encontrados` containing the original segment (matching the existing recognizer behavior for no-significant-token inputs) and no category-level group is added

#### Scenario: category pass is deterministic

- **WHEN** the test calls `detectar_productos("un postre", [...same catalog as before...])` twice with the same supplied catalog
- **THEN** the two results are byte-identical (same `encontrados`, same `encontrados_posibles`, same `encontrados_no_disponibles`, same `no_encontrados`, same `cantidad`, same `texto_origen`, same `producto_presentacion_id` order, same `kind`, same `categoria_nombre`)

#### Scenario: false positives do not increase

- **WHEN** the runner evaluates the 47-case dataset
- **THEN** the 39 currently correct cases remain `correct` (no regression)
- **AND** the 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` (no false promotion)
- **AND** the new category-level signals do NOT promote any case to `unique` when the expected decision is `unknown`

#### Scenario: public recognizer result schema is widened through the typed union

- **WHEN** the test calls `detectar_productos` with any input that triggers the category pass
- **THEN** the returned dict has exactly the four keys `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`
- **AND** each entry in `encontrados` preserves the documented catalog fields (`producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`) plus `cantidad` (int) and `texto_origen` (str)
- **AND** each product-level entry in `encontrados_posibles` has the documented `texto_origen` and `productos` fields and does NOT carry a `kind` field (the existing shape is preserved byte-identically)
- **AND** each category-level entry in `encontrados_posibles` has the documented `kind: "category"`, `categoria_nombre`, and `texto_origen` fields and DOES NOT carry a `productos` list
- **AND** the `FuzzyProductRecognizer.recognize` adapter at `backend/recognizers/fuzzy_product_recognizer.py` continues to delegate to `detectar_productos` and returns the same `ProductRecognizerResult` shape (widened through the union)
- **AND** the `ProductRecognizerResult` protocol at `backend/recognizers/product_recognizer_contract.py` formally types both variants in the `encontrados_posibles` element type
- **AND** the `__all__` of `backend/recognizers/product_recognizer` continues to export exactly `{"detectar_productos"}`

### Requirement: Candidate-compatible category prefixes do not suppress explicit product matches

When evaluating product candidates, the fuzzy recognizer SHALL treat a
significant input token that matches the same candidate's catalog category
(using the existing singular/plural normalization) as context rather than a
required product-name token, but only when at least one other significant
product-identifying token remains and matches that candidate under the existing
key-token rules. It SHALL NOT generate candidates from a category token or
ignore a token for a candidate in another category.

#### Scenario: Explicit category prefix resolves only product candidates in that category

- **WHEN** the input is `3 Pizza napolitana` and the catalog has `Napolitana`
  product-presentations in category `Pizzas` plus unrelated products
- **THEN** the recognizer returns only the existing Napolitana presentation
  candidates with quantity `3`
- **AND** it does not return a category-level group or an unmatched fragment
- **AND** it does not expose an unrelated Pizza or product from another
  category

#### Scenario: Category-only input remains safe ambiguity

- **WHEN** the input is `3 pizza` and there is no product-identifying token
- **THEN** the recognizer keeps the existing category-level ambiguity result
- **AND** it exposes no product IDs as ordinary candidates

#### Scenario: Incompatible category cannot be ignored

- **WHEN** the input category token does not match a candidate's own category
- **THEN** that token remains required under the existing key-token filtering
- **AND** the candidate is not promoted merely because its product name
  otherwise matches
