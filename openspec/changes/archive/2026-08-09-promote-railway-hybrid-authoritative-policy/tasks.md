## 1. Aprobación y selección

- [x] 1.1 Confirmar evidencia repetida: tres reportes elegibles persistentes y p95 bajo 500 ms.
- [x] 1.2 Aprobar este diseño antes de cambiar configuración.
- [x] 1.3 Seleccionar el único reporte candidato mediante JSON seguro, fingerprint/version, política y SHA-256.

## 2. Persistencia y carga en shadow (requiere autorización operativa)

- [x] 2.1 Verificar lectura, hash y estructura loader-compatible del candidato en `/data/novaorders-policy`.
- [x] 2.2 Redeploy de `calibracion` manteniendo `PRODUCT_RECOGNIZER_MODE=shadow`; confirmar mismo hash y JSON legible.
- [x] 2.3 Configurar sólo `HYBRID_AUTHORITATIVE_POLICY_PATH` en `calibracion`; comprobar settings, loader y factory sin activar el modo.

## 3. Activación controlada (requiere autorización operativa separada)

- [x] 3.1 Configurar `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` sólo en `calibracion`.
- [x] 3.2 Verificar deploy sano y carga controlada sin Twilio, tráfico ni textos reales.
- [x] 3.3 Revisar fallback técnico a Fuzzy conforme al contrato existente.

## 4. Rollback y cierre

- [x] 4.1 Validar que volver a `shadow` y redeployar es operativo y no borra evidencia.
- [x] 4.2 No modificar producción, sync, archive, commit ni push como parte de este change sin autoridad explícita.
- [x] 4.3 Documentar evidencia sanitizada, decisión y límites antes de recomendar cualquier fase posterior.
