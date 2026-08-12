# Diseño: verificación post-4.12B de sólo lectura

## Decisión

Separar la preparación documental de toda operación Railway. La evidencia histórica archivada se usa como antecedente y contrato, nunca como lectura del estado actual. Cada consulta usa un target explícito y produce un resumen sanitizado; el siguiente gate depende de una revisión humana de la evidencia del anterior.

## Secuencia operacional propuesta

```text
aprobación por gate
  -> identidad del target + revisión/SHA desplegada
  -> modo configurado/efectivo + ruta/hash/persistencia de política
  -> settings + loader + factory + health (sin tráfico)
  -> logs acotados y sanitizados
  -> decisión humana: mantener / autorizar rollback / autorizar fase nueva
```

G1--G5 son consultas externas y no se ejecutan con este change sin autorización expresa. La comprobación local posible es sólo documental y de contrato: revisar commits, settings, loader, factory, health y la CLI.

## Límites de evidencia

| Necesidad | Fuente autorizable | Resultado permitido | No permitido |
| --- | --- | --- | --- |
| SHA/revisión desplegada | Railway CLI/metadata del deploy | SHA/revisión y estado del deploy | sync, deploy, variables o logs crudos |
| Modo y política | Proceso/controlado del servicio ya desplegado | configured/effective mode, path no secreto, hash, elegibilidad y clase | valores de entorno, JSON completo, escritura o transferencia |
| Health/factory | `/health` y comprobación interna controlada existente | HTTP status y nombre de clase | webhook, texto de cliente, consulta de catálogo o DB mutante |
| Observabilidad | `backend.cli.query_production_logs` con target/since/limit explícitos | conteos y categorías allowlisted | reintentos, consultas DB, Twilio/Ollama o raw lines |

No existe un endpoint de diagnóstico de modo/factory; por eso G2--G4 no se inventan como llamadas HTTP. Si no hay un mecanismo operacional existente que pueda ejecutarse sin ampliar alcance, el gate queda bloqueado y se propone un change posterior; no se añade código ni endpoint en esta fase.

## Contratos de fallback y rollback

El modo inválido es seguro sólo si `effective_mode=fuzzy` y se conserva su categoría sanitizada. En `shadow`, Fuzzy continúa siendo autoridad; en `hybrid_authoritative`, los fallos técnicos internos usan el fallback Fuzzy ya implementado. La falta de `commerce_id` no es un fallback permitido: es un error tipado y bloquea cualquier interpretación positiva de G5.

El único rollback planificado para una fase autorizada posterior es `shadow`. No se borra ni reconstruye el JSON; se debe preservar su hash antes y después del rollback. Un cambio de modo, incluso a `shadow`, es una mutación Railway y requiere su aprobación explícita propia.

## Observabilidad de ventana acotada

La consulta propone una sola ventana temporal corta, `--limit` finito y un filtro local de evento cuando corresponda. El change archivado `add-safe-product-recognition-observability` incorpora `shadow_product_recognition` al catálogo versionado de `query_production_logs`. G5 sólo puede usar esa CLI después de un deploy separadamente autorizado de dicho change al target explícito; hasta entonces, la revisión desplegada no puede devolver este nuevo evento seguro y cualquier resultado vacío es inconcluso. Si Railway no devuelve eventos válidos contra el catálogo luego de ese deploy, G5 se detiene. Los eventos de provider/embedding sólo aportan salud técnica periférica; nunca prueban decisiones de reconocimiento ni tráfico real.

Los únicos campos útiles de 4.12B que podrían agregarse, siempre que la superficie existente los exponga de forma segura, son modo, estrategia, `fallback`, categoría de fallback, decisión híbrida y latencias agregadas. Nunca IDs de candidatos, commerce IDs, correlation IDs, textos ni scores.

## Transacciones y seguridad

Los recognizers y la factory no poseen transacciones; la verificación no ejecuta reconocimiento ni abre sesiones. La consulta de logs no abre base de datos, no invoca Twilio/Ollama y no modifica Railway. Si un mecanismo de verificación existente viola cualquiera de estas propiedades, no se usa.
