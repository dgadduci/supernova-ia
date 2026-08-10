## 1. Aprobación y descubrimiento

- [x] 1.1 Confirmar que `calibracion` aporta evidencia, no autoridad para producción.
- [x] 1.2 Aprobar este diseño antes de cualquier operación de producción.
- [x] 1.3 Inventariar volumen, ruta, modo y compatibilidad de producción sin exponer secretos.

## 2. Artefacto y dependencias de producción (requiere autorización por gate)

- [x] 2.1 Verificar montaje persistente y disponibilidad del artefacto; no asumir la ruta de calibración.
- [x] 2.2 Si falta artefacto, proponer transferencia atómica separada y pedir autorización explícita.
- [x] 2.3 Verificar hash, JSON, loader y factory mientras producción sigue en `shadow`.
- [x] 2.4 Verificar health y embedding/vector de forma controlada, sin Twilio ni textos reales.

## 3. Activación y rollback (requiere autorización por gate)

- [x] 3.1 Configurar policy path en shadow y redeployar producción.
- [x] 3.2 Configurar `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` y redeployar sólo tras gates previos.
- [x] 3.3 Verificar carga/factory/health controlados.
- [x] 3.4 Validar rollback inmediato a shadow y preservar evidencia.

## 4. Cierre

- [x] 4.1 Documentar evidencia sanitizada y decisión.
- [ ] 4.2 No sync, archive, commit, push ni operación adicional sin autoridad explícita.
