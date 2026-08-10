## 1. Aprobación de alcance

- [x] 1.1 Confirmar que esta etapa sólo calibra y revisa: no activa
  `hybrid_authoritative`, no cambia configuración y no ejecuta Twilio.
- [x] 1.2 Confirmar el destino Railway controlado y de sólo lectura para las
  referencias dinámicas del dataset congelado; no usar catálogos, clientes ni
  tráfico real.
- [x] 1.3 Confirmar el mecanismo persistente Railway y su ruta real sólo tras
  comprobar montaje, permisos y supervivencia; no aceptar `/tmp` ni una ruta
  de imagen efímera.

## 2. Operación controlada (requiere aprobación posterior)

- [x] 2.1 Verificar que `PRODUCT_RECOGNIZER_MODE=shadow` y que los gates
  Railway de embedding ya son sanos, sin modificar Tailscale/Ollama/UFW.
- [x] 2.2 Ejecutar el CLI existente una vez con
  `backend/data/product_recognition_calibration_cases.json`; conservar sólo
  salida sanitizada y el reporte seguro para revisión.
- [x] 2.3 Revisar `eligibility.status` como veredicto autoritativo. Si no es
  `eligible`, detenerse y mantener shadow.
- [x] 2.4 Si es `eligible`, verificar persistencia, hash y lectura del reporte
  desde el montaje Railway confirmado. No configurar todavía la ruta runtime.

## 3. Revisión y siguiente fase

- [ ] 3.1 Aportar salida completa de las validaciones locales y evidencia
  Railway sanitizada para revisión de Codex.
- [x] 3.2 Proponer un cambio separado para cualquier configuración controlada
  de `hybrid_authoritative`; requiere artefacto persistente, verificación
  controlada y aprobación explícita.
- [ ] 3.3 No sync/archive/commit/deploy en este cambio sin autorización
  independiente.
