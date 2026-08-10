## 1. Aprobación de alcance

- [x] 1.1 Confirmar que la necesidad es caracterizar p95 repetido por encima de 500 ms, no elevar el presupuesto de elegibilidad.
- [x] 1.2 Confirmar que el origen es exclusivamente el dataset congelado y Railway `calibracion`, sin tráfico ni datos reales.
- [x] 1.3 Aprobar el diseño de observabilidad agregada antes de implementar.

## 2. Instrumentación de runner

- [x] 2.1 Definir una representación interna simple para duraciones y conteos por etapa, sin texto de caso ni excepciones crudas.
- [x] 2.2 Medir fuzzy, embedding, vector y evaluación sin modificar decisiones, candidatos, fallback ni ownership transaccional.
- [x] 2.3 Añadir `latency_breakdown` agregado al reporte, preservando el contrato de `eligibility` y los campos existentes.
- [x] 2.4 Clasificar fallos por categorías seguras y estables, sin detalles de proveedor ni evidencia por caso.

## 3. Tests y validación

- [x] 3.1 Cubrir agregados de duración y ausencia de campos sensibles.
- [x] 3.2 Cubrir fallo de embedding/vector como conteo seguro sin alterar fallback, candidatos ni elegibilidad.
- [x] 3.3 Ejecutar pytest focalizado, Ruff y compileall; el usuario aportará salida completa de los comandos que dependan de `venv`.
- [x] 3.4 Ejecutar `openspec validate characterize-controlled-calibration-latency --strict` y `git diff --check`.

## 4. Operación posterior, sólo con nueva autorización

- [x] 4.1 Desplegar la instrumentación en `calibracion`; no tocar producción.
- [x] 4.2 Ejecutar varias corridas sin `--diagnose`, cada una con archivo persistente nuevo bajo `/data/novaorders-policy`.
- [x] 4.3 Revisar sólo agregados seguros, `eligibility` y persistencia.
- [x] 4.4 Mantener `PRODUCT_RECOGNIZER_MODE=shadow` durante la caracterización; no promover, sync, archive, commit ni push como parte de este change sin autoridad explícita.
