# Extender programación de entrega con expresiones temporales españolas acotadas

## Objetivo

Extender el intent ya desplegado `set_fecha_hora_entrega` para reconocer, de forma determinista y sin LLM como autoridad, un subconjunto pequeño de expresiones españolas que contienen fecha y hora completas. La única persistencia sigue siendo el reemplazo de `Pedido.datetime_entrega_programada` del borrador propio de la sesión activa.

## Recorrido actual verificado

`IntentClassifier` ya clasifica el intent (el prompt lo registra y el corpus controlado contiene `Lo quiero recibir mañana a las 20`). Sin contexto pendiente, `initial_intent_dispatcher` invoca `process_initial_set_fecha_hora_entrega` en `draft_order_closure`. El handler comprueba sesión activa, `session.id_pedido`, ownership y `BORRADOR`; parsea sólo los dos formatos absolutos existentes y deja el commit/rollback a `process_incoming_message_transactional` o al coordinador provider. `outbound_response_mapper` reutiliza el builder de cierre para la respuesta local y el outbox.

El cambio archivado `2026-08-12-set-draft-order-delivery-schedule` ya implementó esa base. Este cambio es independiente y no la modifica.

## Alcance y contrato mínimo recomendado

Se conserva el formato absoluto actual y se añaden únicamente frases que, tras normalización determinista de mayúsculas, espacios y acentos, expresen una fecha relativa inequívoca y una hora inequívoca:

- `hoy a las H`, `hoy a las H horas`, `hoy a las H:MM`, `hoy a las H:MM horas`;
- `mañana a las H`, `mañana a las H horas`, `mañana a las H:MM`, `mañana a las H:MM horas`;
- las mismas formas con calificadores exactos `de la mañana`, `de la tarde` o `de la noche` cuando la hora de 1–12 se traduce sin ambigüedad a 24 horas;
- día de semana próximo (`lunes` a `domingo`), con `el` opcional, seguido de `a las` y una hora de las mismas formas. El próximo día es la siguiente ocurrencia estrictamente futura; si hoy es el mismo día, se usa hoy sólo si la hora sigue siendo futura; en caso contrario, la semana siguiente.

Se permite texto envolvente no temporal alrededor de un único fragmento reconocido (por ejemplo, `Quiero que me lo envíes hoy a las 22 horas`), pero no más de un fragmento temporal ni números/horas que hagan incierta la extracción. Las formas absolutas existentes mantienen su requisito de entrada completa, salvo `strip()`.

Ejemplos: `hoy a las 22 horas`, `mañana a las 6 de la tarde` y `el viernes a las 20` son válidos si resultan futuros. `a las 11 de la noche` solicita fecha; `hoy a las 22` ya pasada solicita un horario futuro sin saltar a mañana.

Se rechazan sin modificar el pedido: `En dos horas`, `A las 8`, `Al mediodía`, `Entre 19 y 20`, `Tipo 8`, `Mañana temprano`, rangos, ventanas, recurrencias, duraciones, fechas relativas distintas de hoy/mañana, offsets y zonas del mensaje. No se aceptan inferencias de fecha ni de AM/PM cuando falta el calificador.

## Outcomes, fallback y transacción

- `executed`: expresión admitida, completa y futura; reemplaza sólo el datetime.
- `rejected` / `needs_date`: hora inequívoca sin fecha. Respuesta pide día/fecha y hora; no crea contexto pendiente.
- `rejected` / `past_datetime`: fecha relativa resuelta pero ya pasada. Respuesta pide un horario futuro; no se avanza a mañana.
- `rejected` / `invalid_format`: expresión vaga, relativa no contratada, rango, duración, formato inválido o extracción incierta.
- Rechazos de boundary preexistentes: `session_not_active`, `no_draft`, `session_mismatch`, `pedido_not_borrador`.

No hay fallback de ejecución ni reinterpretación: no LLM, Fuzzy, otro handler, búsqueda de pedido ni cambio de intent. Fuzzy sigue siendo el fallback seguro de reconocimiento de productos y no interviene aquí. Un contexto pendiente conserva su prioridad existente. Excepciones técnicas se propagan al dueño transaccional exterior.

## Límites de arquitectura

- Zona y reloj autoritativos: `America/Argentina/Buenos_Aires`; el reloj se inyecta o se pasa como dependencia testeable al parser/validador.
- El handler no llama `commit`, `rollback`, `flush`, `refresh`, `begin` ni `close`.
- Las respuestas y `resolved_data` nunca exponen datetime completo, zona, texto de entrada, ids ni detalle técnico. En éxito usan sólo una etiqueta de forma segura; en rechazo, sólo razón estable.
- No cambia requisitos de confirmación ni dirección, observaciones, productos, candidatos, método de entrega, pago, confirmación, cancelación, estado o sesión.

## No-goals

No prompt/corpus/calibración salvo evidencia posterior indispensable; no LLM temporal, endpoints, workers, migraciones, geocoding, zonas por comercio, recurrencias, rangos, ventanas, duración relativa, borrado, LangGraph ni refactor fuera de esta ruta.

## Archivos esperados

- `backend/intents/orchestration/draft_order_closure.py`
- `backend/intents/responses/draft_order_closure.py`
- `backend/tests/test_draft_order_closure.py`
- `backend/tests/test_outbound_response_mapper.py`
- `backend/tests/test_transactional_message_processor.py` sólo si hace falta ampliar evidencia de rollback exterior

No se esperan cambios en `prompt_template.py`, `intent_corpus.py`, clasificador ni dispatcher/mapper, salvo que la implementación demuestre una necesidad estricta y aprobada.

## Observabilidad, validación y reversibilidad

No se agregan logs o eventos que contengan texto recibido o datetime. Las métricas/diagnósticos existentes, si los hubiera en la ruta, sólo podrán usar outcome/razón estables.

El usuario ejecutará localmente y compartirá la salida completa:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py backend/tests/test_transactional_message_processor.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/draft_order_closure.py backend/intents/responses/draft_order_closure.py backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py backend/tests/test_transactional_message_processor.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/draft_order_closure.py backend/intents/responses/draft_order_closure.py
openspec validate extend-draft-order-delivery-schedule-spanish-expressions --strict
git diff --check
```

Revertir el cambio vuelve al parser absoluto previo sin migración. Los datetimes ya persistidos permanecen y no se modifica ningún esquema. Quedan diferidos lenguaje relativo adicional, ventanas, rangos, duración, recurrencia y el flujo conversacional con contexto de aclaración.

## Subfase de regresión: preservar expresión temporal completa

### Evidencia y objetivo

En producción, el mensaje `Quiero que me lo envíes mañana a las 8 de la noche` recibió el rechazo de formato. El parser determinista admite ese texto completo. La causa verificada es de boundary: `IntentClassifier` permite que cada `ClassifiedIntent.mensaje` sea sólo un substring literal, y el dispatcher entrega ese substring al handler. Si el modelo devuelve `a las 8`, el handler pierde `mañana` y `de la noche` y lo rechaza correctamente como ambiguo.

El objetivo de esta subfase es que el handler de programación reciba el mensaje original completo del turno, para que su parser determinista pueda extraer el único fragmento temporal contratado.

### Scope y contrato de corrección

Únicamente el branch `SET_FECHA_HORA_ENTREGA` de `initial_intent_dispatcher` SHALL invocar `process_initial_set_fecha_hora_entrega` con el argumento `message` original de `dispatch_initial_message`, no con `classified.mensaje`. No se cambia la clasificación ni la secuencia de intents; el `ProcessedIntent.source_text` resultante será el mensaje original completo en este intent.

El parser ya exige a lo sumo un fragmento temporal permitido y rechaza múltiples fragmentos; por ello reutilizar el mensaje completo no autoriza inferencia ni amplía el contrato temporal. Si un turno contiene dos expresiones temporales, ambos procesamientos de programación se rechazan con `invalid_format`, sin escritura. Los demás intents mantienen `classified.mensaje` como entrada, sin cambios.

### No-goals y límites

No se modifica prompt, corpus, schema de clasificación, LLM, Fuzzy, parser temporal, respuestas, mapper, transacciones, endpoints, migraciones ni observabilidad. No se intenta reconstruir ni complementar substrings del modelo. No se cambia la prioridad de contextos pendientes.

### Archivos y pruebas adicionales

- `backend/intents/orchestration/initial_intent_dispatcher.py`
- `backend/tests/test_draft_order_closure.py` o un test focalizado del dispatcher existente

Las pruebas SHALL simular un `SET_FECHA_HORA_ENTREGA` cuyo `classified.mensaje` sea el substring ambiguo `a las 8`, con `dispatch_initial_message(..., message="Quiero que me lo envíes mañana a las 8 de la noche")`, y verificar que el handler recibe el mensaje original completo. También SHALL verificar que otro intent continúa recibiendo su substring clasificado y que dos fragmentos temporales no persisten programación.

La validación local adicional será:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_closure.py backend/tests/test_intent_classifier.py backend/tests/test_transactional_message_processor.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/tests/test_draft_order_closure.py backend/tests/test_intent_classifier.py backend/tests/test_transactional_message_processor.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/initial_intent_dispatcher.py
openspec validate extend-draft-order-delivery-schedule-spanish-expressions --strict
git diff --check
```

Revertir el único branch de dispatcher restablece el comportamiento previo sin modificar datos ni schema. La corrección se implementará sólo tras nueva aprobación explícita.
