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
The function SHALL accept `productos_presentaciones` as a list of dicts with the spec's shape: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`. A catalog item missing `producto_presentacion_id` is ignored. The fields `producto_id` and `presentacion_id` are required (the caller is responsible for converting from the DB model to this shape; legacy data is converted before being passed to the recognizer).

#### Scenario: Catalog item without id is ignored
- **WHEN** the test calls `detectar_productos("pizza", [{"producto_nombre": "Pizza"}, {"producto_presentacion_id": 1, "producto_nombre": "Pizza"}])`
- **THEN** the result reflects only the second item (with id)

#### Scenario: activo defaults to True when missing
- **WHEN** the test calls the function with a catalog item that does NOT have an `activo` field but has `disponible: True`
- **THEN** the item is treated as available (the absence of `activo` is interpreted as `True`)

#### Scenario: presentacion_descripcion may be empty
- **WHEN** the test calls the function with a catalog item that has an empty `presentacion_descripcion` (matching the legacy data shape, where the equivalent was `tamanio` mapped to `presentacion_codigo`)
- **THEN** the item is still recognized for presentation matching; the match uses `presentacion_codigo`

### Requirement: Product matching against producto_nombre
The function SHALL match the user text against each catalog item's `producto_nombre` (with the legacy fuzzy pipeline: text normalization, quantity words, stopwords, product aliases, phonetic substitutions, prefix matching, segmentation, quantity extraction, RapidFuzz scoring).

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
The subphase SHALL NOT introduce a router, a FastAPI endpoint, a service class, a recognizer-adapter, persistence, a `print` statement, debug CLI code, or any other runtime concern. The only new code is the recognizer module, the empty `__init__.py`, and the verification test.

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