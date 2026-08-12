# Persistir dirección de entrega del pedido borrador

## Objective

Persistir una dirección concreta clasificada como `set_direccion_entrega` en el `Pedido` borrador de la sesión activa y responder sin fallback genérico.

## Current execution path

La calibración ya clasifica `Me lo envías a Tilcara 2020` como `set_direccion_entrega`, pero el dispatcher inicial y el mapper no tienen branch para ese intent. El resultado es rechazo y fallback genérico. `Pedido` tiene `observaciones`, pero no una dirección. El head Alembic es `b0c1d2e3f4a5`.

Se reutiliza el camino de observación: clasificador, dispatcher, orchestrator de cierre, transacción externa, mapper y outbox. Ese camino usa `session.id_pedido`, comprueba sesión activa, propiedad del pedido y `borrador`, y no posee transacciones.

## Scope and non-goals

- Agregar `pedidos.direccion_entrega` como `Text` nullable y una migración desde `b0c1d2e3f4a5`.
- Agregar handler de borrador, branch de dispatcher, respuesta privada y tests focalizados.
- No recalibrar el clasificador ni reabrir observación/dirección.
- No geocoding, zonas, parsing, endpoints, productos, candidatos pendientes, inferencia de método, confirmación, cancelación, pago, fecha, worker ni refactor.

## Shared boundary, fallback and transactions

El único target válido es `session.id_pedido`. El handler exige sesión activa, pedido existente, `pedido.id_session == session.id` y estado `borrador`. Normaliza NFKC, trim y whitespace interno; admite 1–500 code points y reemplaza el valor previo. El campo es independiente de ambas observaciones.

Entrada válida: `executed`. Sesión/pedido inválido, texto vacío o mayor a 500: `rejected`, sin mutar. Excepción técnica: se propaga al dueño transaccional actual. No hay fallback a observación, reconocimiento ni otro pedido/comercio. El handler no hace commit, rollback, flush, refresh, begin ni close.

## Observability

`resolved_data` expone sólo `accepted_length` o una razón estable. La respuesta no repite la dirección. No se agregan logs, eventos ni pipelines con el texto.

## Expected files and validation

- `backend/models/pedido.py`, una revisión Alembic, cierre de pedido, dispatcher, respuestas, mapper y tests focalizados.
- Esta propuesta y su delta.

El usuario ejecutará localmente:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_observation.py backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/models/pedido.py backend/alembic/versions backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py backend/tests/test_draft_order_observation.py backend/tests/test_draft_order_closure.py backend/tests/test_outbound_response_mapper.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/pedido.py backend/alembic/versions backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py
openspec validate set-draft-order-delivery-address --strict
git diff --check
```

## Rollback and deferred limitations

Routing y respuesta son reversibles. El downgrade elimina solamente la columna y requiere aprobación explícita con datos productivos. Direcciones estructuradas, zonas, requisito de confirmación y exposición API quedan diferidos.
