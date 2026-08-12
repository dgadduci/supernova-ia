# Ejecutar fecha y hora programada de entrega

## Objetivo

Ejecutar `set_fecha_hora_entrega` sobre el pedido borrador de la sesión activa y persistir únicamente `Pedido.datetime_entrega_programada`. No se cambia clasificación, prompt ni corpus.

## Hechos verificados

- `IntentName.SET_FECHA_HORA_ENTREGA` y el campo nullable `DateTime(timezone=True)` ya existen.
- El dispatcher y el mapper no tienen branch; por ello hoy termina en fallback genérico.
- `PedidoService.set_fecha_entrega` no es apto para conversación: llama `flush`, `commit`, `refresh` y `rollback`, y no comprueba ownership de sesión.
- El pipeline local conserva transacción en `process_incoming_message_transactional`; proveedor, en `ProviderInboundMessageCoordinator.process_lease`.
- No hay parser temporal ni timezone de negocio compartida.
- La base actual está alineada con `origin/main` en `0318a6d` e incluye la migración archivada `c1d2e3f4a5b6_add_pedidos_direccion_entrega.py`.

## Scope

- Handler en el cierre de pedido, branch de dispatcher, builder de respuesta y branch del mapper.
- Parser estricto, validación temporal, reemplazo y pruebas focalizadas.
- No se crea migración: se usa exclusivamente la columna existente.

## No-goals

- Endpoint HTTP, schema, modelo, `PedidoService`, migración, recognizers, prompt/corpus o calibración.
- Fecha sola, hora sola, lenguaje relativo, rangos, recurrencia, timezone por comercio, geocoding y borrado explícito.
- Productos, observaciones, dirección, pago, método, confirmación, cancelación, candidatos pendientes o LangGraph.

## Contrato propuesto para aprobación

Se acepta sólo una fecha y hora absolutas, sin texto extra, tras `strip()`:

- `DD/MM/YYYY HH:MM`
- `YYYY-MM-DD HH:MM`

La zona autoritativa es `America/Argentina/Buenos_Aires`, mediante `zoneinfo.ZoneInfo`. La fecha/hora debe ser futura frente al reloj de esa zona. Una entrada válida reemplaza la previa. Formato incompleto, ambiguo, con offset, relativo, texto adicional, inválido o pasado se rechaza y conserva el valor anterior. No se infiere ni completa información.

## Boundary, outcomes y fallback

El handler exige sesión activa, usa sólo `session.id_pedido`, verifica `pedido.id_session == session.id` y `BORRADOR`, y sólo entonces asigna el datetime.

- `executed`: datetime completo, válido y futuro.
- `rejected`: `session_not_active`, `no_draft`, `session_mismatch`, `pedido_not_borrador`, `invalid_format` o `past_datetime`.
- Falla técnica: se propaga al owner exterior para rollback del turno.

No hay fallback de ejecución: no fuzzy, LLM, otro handler ni búsqueda alternativa. Un pending context conserva prioridad. Un inválido no cae a observación, dirección ni método de entrega.

## Transacción, privacidad y observabilidad

Handler, dispatcher, builder y mapper no llaman `commit`, `rollback`, `flush`, `refresh`, `begin` ni `close`. La respuesta fija no muestra fecha/hora, zona, ids ni texto de entrada. `resolved_data` contiene únicamente una razón estable en rechazo o un indicador seguro del formato aceptado en éxito; nunca el datetime completo. No se agregan logs/eventos con el mensaje. Mapper local y outbox producen el mismo texto.

## Archivos esperados

- `backend/intents/orchestration/draft_order_closure.py`
- `backend/intents/orchestration/initial_intent_dispatcher.py`
- `backend/intents/responses/draft_order_closure.py`
- `backend/services/outbound_response_mapper.py`
- `backend/tests/test_draft_order_closure.py`
- `backend/tests/test_outbound_response_mapper.py`
- `backend/tests/test_transactional_message_processor.py` (sólo si requiere ampliar la cobertura de rollback exterior)

## Validación local

El usuario ejecutará y compartirá salida completa:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py backend/tests/test_transactional_message_processor.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py backend/tests/test_transactional_message_processor.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py
openspec validate set-draft-order-delivery-schedule --strict
git diff --check
```

## Rollback y límites diferidos

Revertir los branches elimina ejecución sin migración; valores ya guardados se conservan. Borrado, lenguaje relativo, zonas/horarios por comercio, ventanas y mostrar la programación en el resumen quedan diferidos.
