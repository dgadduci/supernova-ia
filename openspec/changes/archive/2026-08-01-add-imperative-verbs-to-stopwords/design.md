## Context

`backend.recognizers.product_recognizer.detectar_productos` (línea 443) recibe un texto libre y un catálogo de `producto_presentacion`, y devuelve un dict con cuatro claves. Antes de aceptar un candidato, le aplica `_filtrar_por_tokens_clave` (línea 299), que exige que todos los tokens significativos del mensaje del usuario estén presentes (con tolerancia fuzzy) en los tokens significativos del nombre del producto.

`STOPWORDS` (línea 19) contiene palabras funcionales y verbos de petición (`mandame`, `quiero`, `dame`, `traeme`, `pedir`, etc.) que el filtro descarta antes de comparar. Los verbos imperativos de acción sobre el pedido (`quita`, `quitar`, `saca`, `sacame`, `sacala`, `elimina`, `remueve`, `borra`, `suprime`) no están incluidos, así que cuentan como tokens significativos y descartan candidatos cuyo nombre no los contenga.

Para `agregar_producto`, el problema se disfraza porque `_segmentar_pedido` corta el mensaje cuando aparece una cantidad explícita (ej. `"agrega 2 empanadas de pollo"` → segmentos `["agrega"]` y `["2 empanadas de pollo"]`). Sin cantidad, el mensaje completo queda como un único segmento y el verbo lo descarta.

Para `quitar_producto`, el flujo típico no incluye cantidad y el síntoma es exactamente el reportado: el usuario pide quitar y el sistema responde `"Ese producto no está en tu pedido."`.

El handler `execute_quitar_producto` ya implementa correctamente el contrato "sin cantidad → eliminar la línea completa" (`backend/intents/handlers/quitar_producto_handler.py:97`), pero nunca se invoca porque el orchestrator solo lo ejecuta cuando hay un único `pedido_producto_id` resuelto, y eso requiere que `detectar_productos` haya producido al menos un candidato.

## Goals / Non-Goals

**Goals:**
- Que `detectar_productos` reconozca productos cuando el mensaje del usuario incluye verbos imperativos de remover u otros verbos de acción sobre el pedido.
- Que `quitar_producto` sin cantidad explícita llegue al handler y elimine la línea completa del pedido, devolviendo `"Quité <producto> de tu pedido."`.
- Que `agregar_producto` sin cantidad explícita también reconozca el producto (caso hoy roto por la misma causa).
- Cambio mínimo, sin refactor.

**Non-Goals:**
- No se modifica la API ni la forma del resultado de `detectar_productos`.
- No se introducen dependencias nuevas ni cambios en DB / routers / schemas.
- No se ajusta la lógica de matching más allá de extender el set literal `STOPWORDS`.

## Decisions

- **Decisión: extender `STOPWORDS` con verbos imperativos.** Es el punto único donde el filtro de tokens significativos decide qué descartar. Cualquier otra alternativa (preprocesar el mensaje en `quitar_producto_recognizer` o agregar lógica nueva en `_filtrar_por_tokens_clave`) duplica lógica o añade una segunda ruta de limpieza.
- **Verbos a incorporar (normalizados a minúsculas sin tildes, igual que el resto del set):**
  - Quitar / sacar / remover / eliminar / borrar / suprimir en imperativo y infinitivo: `quita`, `quitar`, `saca`, `sacame`, `sacala`, `quitala`, `quitalas`, `quitale`, `sacasela`, `elimina`, `eliminar`, `remueve`, `remover`, `borra`, `borrar`, `suprime`, `suprimir`.
  - Se omiten formas con pronombres adicionales (`sacanos`, `quitenme`) para no inflar el set; pueden cubrirse en una iteración posterior si aparecen casos.
- **Alternativas consideradas:**
  - *Preprocesar en `quitar_producto_recognizer` antes de llamar a `detectar_productos`*: rejected. Rompe el contrato de que `recognize_quitar_producto` solo pasa por el fuzzy pipeline, y deja el bug latente para `agregar_producto`.
  - *Hacer la comparación de tokens menos estricta en `_filtrar_por_tokens_clave`*: rejected. Cambia la semántica de matching para todos los casos y abre la puerta a falsos positivos.
  - *Crear un set `IMPERATIVE_VERBS` separado*: rejected. Es la misma categoría conceptual que `STOPWORDS` desde el punto de vista del filtro (palabras a ignorar al comparar tokens), y mantener un solo set evita coordinación entre dos colecciones.

## Risks / Trade-offs

- **Falsos negativos si un nombre de producto contiene un verbo del set.** → Mitigación: los verbos seleccionados (`quita`, `saca`, `elimina`, etc.) no son candidatos plausibles como nombre de producto. Si en el futuro se diera el caso, se prefiere que el usuario reformule.
- **Cobertura incompleta de conjugaciones regionales** (`sacanos`, `quitame`, etc.). → Mitigación: el cambio es un `frozenset` editable; agregar variantes es trivial y se puede extender si surgen reportes.
- **No resuelve verbos con pronombres clíticos compuestos** (`sacámelas`, `quítenmela`). → Mitigación: queda fuera de scope; seguir la convención del resto del set y solo cubrir las formas más comunes.
- **Cambio en el reconocimiento podría exponer matches nuevos no deseados** en intents distintos (`modificar_producto`). → Mitigación: estos verbos son de remover, no encajan con la intención `modificar_producto`; el clasificador LLM los etiqueta como `quitar_producto` antes de llegar al recognizer.