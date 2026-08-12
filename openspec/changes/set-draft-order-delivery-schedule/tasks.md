# Tasks

## 1. Especificación y aprobación

- [x] 1.1 Actualizar contra `origin/main` e inspeccionar instrucciones, OpenSpec, modelo, migraciones, servicio/router/schema, dispatcher, cierre, respuestas, mapper, transacciones y tests.
- [x] 1.2 Confirmar intent/campo existentes, branches faltantes y que `PedidoService.set_fecha_entrega` no sirve para conversación.
- [x] 1.3 Definir formato, zona, rechazos, reemplazo, privacidad, fallback, no-migración y límites.
- [x] 1.4 Obtener aprobación explícita antes de implementar.

## 2. Implementación posterior a aprobación

- [x] 2.1 Usar la columna existente; no crear migración.
- [x] 2.2 Agregar parser estricto, comparación temporal testeable y handler sin ownership transaccional.
- [x] 2.3 Agregar branches de dispatcher, respuesta y mapper.
- [x] 2.4 Cubrir los dos formatos exactos, zona, reemplazo/rechazo, aislamiento, prioridad, privacidad (sin datetime en `resolved_data`), mapper/outbox y rollback exterior.

## 3. Validación y handoff

- [x] 3.1 Usuario ejecuta los comandos de `proposal.md` y entrega salida completa.
- [ ] 3.2 Codex revisa código y salida antes de aprobar.
- [ ] 3.3 No commit, sync, archive ni deploy sin autorización separada.
