# Tasks

## 1. Especificación y aprobación

- [x] 1.1 Actualizar contra `origin/main` e inspeccionar instrucciones, spec archivado, prompt/corpus, dispatcher, cierre, mapper, owner transaccional y tests focalizados.
- [x] 1.2 Confirmar que la base implementada ya tiene intent, campo, branches, aislamiento, timezone y respuesta fija.
- [x] 1.3 Definir contrato español acotado, outcomes, reloj inyectable, privacidad, fallback y límites.
- [ ] 1.4 Obtener aprobación explícita antes de implementar.

## 2. Implementación posterior a aprobación

- [ ] 2.1 Extender exclusivamente el parser/validador temporal con reloj testeable y sin LLM.
- [ ] 2.2 Agregar razones y respuestas privadas para `needs_date`, `past_datetime` e `invalid_format` sin crear pending context.
- [ ] 2.3 Cubrir formatos absolutos conservados; hoy/mañana; día semanal; tarde/noche; bordes de reloj; reemplazo; aislamiento; entrada rechazada; privacidad; mapper/outbox; rollback exterior.
- [ ] 2.4 Mantener prompt/corpus sin cambios, salvo evidencia indispensable aprobada aparte.

## 3. Validación y handoff

- [ ] 3.1 Usuario ejecuta los comandos locales exactos de `proposal.md` y comparte salida completa.
- [ ] 3.2 Codex revisa código, salida, alcance y estado de tareas.
- [ ] 3.3 Sólo con autorización separada: commit, integración/sync, archive o deploy.

## 4. Regresión de fuente temporal detectada en producción

- [x] 4.1 Diagnosticar que `ClassifiedIntent.mensaje` puede ser substring y que el dispatcher lo entrega al handler temporal.
- [x] 4.2 Revisar este change activo con el contrato acotado de preservar el mensaje original sólo para `set_fecha_hora_entrega`.
- [x] 4.3 Obtener aprobación explícita antes de modificar dispatcher o pruebas.
- [x] 4.4 Implementar el branch focalizado y pruebas de substring temporal, aislamiento de otros intents y múltiples fragmentos.
- [ ] 4.5 Usuario ejecuta validación local, Codex revisa la salida completa y se repite la prueba E2E antes de archivar.
