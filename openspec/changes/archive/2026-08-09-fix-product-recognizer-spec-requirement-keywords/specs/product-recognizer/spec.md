## MODIFIED Requirements

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
