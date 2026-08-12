## 1. Preparación documental

- [x] 1.1 Inspeccionar estado git y confirmar commits locales relevantes: `84f414c`, `13a6b71`, `0615a22`.
- [x] 1.2 Revisar los antecedentes archivados de calibración/promoción Railway y la evidencia histórica de producción.
- [x] 1.3 Verificar los límites actuales de settings, loader, factory, health y observabilidad sin leer secretos ni hacer tráfico externo.
- [x] 1.4 Definir explícitamente que la evidencia histórica no prueba el estado actual de producción.

## 2. Gates operacionales posteriores (todos requieren autorización explícita, uno por uno)

- [x] 2.1 Obtener identidad explícita del target Railway y revisión desplegada:
  `production` / `supernova-ia`, deploy `d9a880c3-1d2e-4bdc-be5d-f9b24917ca11`,
  `SUCCESS`, `main` / `56dc455`.
- [x] 2.2 Comprobar modo y política sin contenido ni secretos:
  `configured_mode=hybrid_authoritative`,
  `effective_mode=hybrid_authoritative`, política elegible, loader cargado,
  ruta persistente bajo `/data/novaorders-policy` y SHA-256 registrado en la
  evidencia operacional autorizada.
- [x] 2.3 Comprobar settings, loader, factory y `/health` de forma controlada:
  factory `HybridAuthoritativeProductRecognizer` y `/health` HTTP 200; sin
  mensajes, Twilio, catálogo ni mutaciones.
- [x] 2.4 Ejecutar una ventana de observabilidad acotada y sanitizada mediante
  `query_production_logs`: desde `2026-08-12T15:13:12Z`, límite 100,
  `shadow_product_recognition`, resultado `count=0`; inconcluso, sin inferir
  tráfico ni calidad de reconocimiento.
- [x] 2.5 Revisar evidencia completa: el usuario aprobó mantener
  `hybrid_authoritative`; no se autorizó ni ejecutó rollback, cambio de modo,
  redeploy adicional ni fase correctiva.

## 3. Validación y aprobación

- [x] 3.1 Usuario ejecutó y aportó salida completa de `openspec validate
  verify-post-4-12b-production-state --strict`.
- [x] 3.2 Usuario ejecutó `git diff --check` sin salida.
- [x] 3.3 El usuario aprobó explícitamente el diseño y cada gate externo antes
  de su ejecución.
