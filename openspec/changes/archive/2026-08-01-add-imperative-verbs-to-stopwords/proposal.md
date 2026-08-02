## Why

`detectar_productos` filtra candidatos cuyos nombres no contengan todos los tokens significativos del mensaje del usuario. Los verbos imperativos (`quita`, `saca`, `elimina`, etc.) no forman parte de `STOPWORDS` y, al tener más de 2 letras, sobreviven al filtro, provocando que el candidato sea rechazado aunque el producto sí esté en el catálogo.

Esto bloquea la intención `quitar_producto` cuando el usuario omite la cantidad: `"quita las empanadas de pollo"` retorna `encontrados=[]` y la respuesta al cliente es `"Ese producto no está en tu pedido."`, cuando el handler `execute_quitar_producto` ya soporta borrar la línea completa cuando `cantidad_value is None`.

El mismo defecto afecta a `agregar_producto` sin cantidad explícita (ej. `"agrega empanadas de pollo"`).

## What Changes

- Agregar verbos imperativos de remover (`quita`, `quitar`, `saca`, `sacame`, `sacala`, `quitala`, `quitalas`, `quitale`, `sacasela`) y otros verbos genéricos de acción sobre el pedido (`elimina`, `eliminar`, `remueve`, `remover`, `borra`, `borrar`, `suprime`, `suprimir`) al set `STOPWORDS` en `backend/recognizers/product_recognizer.py`.
- Ningún cambio breaking en la API ni en la forma del resultado de `detectar_productos`.
- Cobertura nueva en tests unitarios para los verbos en escenarios `quitar_producto` y `agregar_producto` sin cantidad explícita.

## Capabilities

### New Capabilities
- `product-recognizer-stopwords`: ninguna. La regla de stopwords se incorpora a la capability existente.

### Modified Capabilities
- `product-recognizer`: agregar un requisito que establezca que verbos imperativos de remover y verbos genéricos de acción sobre el pedido son tratados como stopwords (no participan en la comparación token-a-token).

## Impact

- `backend/recognizers/product_recognizer.py`: extender el set literal `STOPWORDS` (línea 19).
- `backend/tests/test_product_recognizer.py` y/o tests de los recognizers de quitar/agregar: añadir casos que cubran el mensaje sin cantidad con verbo al frente.
- Sin cambios en DB, routers, schemas, ni servicios.
- Sin dependencias nuevas.