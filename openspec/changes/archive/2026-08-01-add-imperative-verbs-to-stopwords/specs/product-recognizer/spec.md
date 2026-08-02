## ADDED Requirements

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