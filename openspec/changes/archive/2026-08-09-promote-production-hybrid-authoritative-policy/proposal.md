# Promover política híbrida autoritativa a producción

## Objetivo

Definir una promoción separada, controlada y reversible de `PRODUCT_RECOGNIZER_MODE=shadow` a `hybrid_authoritative` en producción, sólo después de verificar que producción posee un artefacto de política elegible, persistente y loader-compatible. La evidencia de `calibracion` es un prerrequisito, no una sustitución de esa verificación.

## Estado de partida

En `calibracion` se verificaron tres reportes elegibles del dataset congelado, un artefacto persistente con SHA-256 registrado, carga por factory, salud HTTP y rollback a `shadow`. Producción sigue fuera de esta operación y puede diferir en volumen, ruta disponible, catálogo, embeddings, vector index, configuración de Ollama, datos y carga.

## Alcance

- Inventariar en producción, sin imprimir secretos, la disponibilidad de un volumen persistente, una ruta concreta y la legibilidad de un artefacto de política.
- Verificar que un único reporte elegido sea íntegro, elegible y loader-compatible en el montaje de producción; no asumir que el volumen de `calibracion` es compartido.
- Definir una transferencia o reproducción del artefacto únicamente si la persistencia de producción está verificada y con autorización operacional posterior.
- Verificar producción en `shadow` antes de activar: settings, loader, factory, salud y condiciones mínimas de embedding/vector sin usar mensajes reales.
- Activar `hybrid_authoritative` sólo con evidencia de los gates previos, observación acotada y rollback inmediato a `shadow`.

## No objetivos

- No cambiar dataset, política, umbrales, recognizers, modelos, embeddings, índices, vector search, timeouts, Tailscale, UFW, Docker, migraciones ni código.
- No Twilio/WhatsApp E2E, tráfico sintético por webhook, datos de clientes, pedidos, sesiones ni mensajes reales.
- No reutilizar por suposición una ruta o volumen de `calibracion`; no usar `/tmp`, la capa de imagen ni reportes archivados.
- No sync, archive, commit, push ni deploy de producción en esta etapa de planificación.

## Gates y fallback

| Gate | Evidencia | Si falla |
| --- | --- | --- |
| Persistencia | Montaje y ruta reales de producción, lectura JSON y hash | Mantener producción en `shadow` |
| Artefacto | Elegible, `selected_policy` válida y SHA-256 registrado | No configurar path |
| Dependencias | Embedding/vector controlados y health sanos | Mantener `shadow` |
| Carga | Settings, loader y factory en `shadow` aceptan el artefacto | No cambiar modo |
| Activación | Deploy sano y observación autorizada | Rollback inmediato a `shadow` |
| Rollback | Modo shadow restaurado sin borrar evidencia | Bloquear expansión |

Fuzzy es el fallback seguro. Los fallos técnicos de la ruta híbrida conservan el fallback interno existente; fallos de configuración, artefacto o deploy fuerzan mantener/restaurar `shadow`.

## Transacciones, seguridad y reversibilidad

No hay mutaciones de PostgreSQL ni ownership de transacciones. La única posible escritura futura sería una transferencia atómica y explícitamente autorizada del JSON elegido al volumen de producción; se validará por SHA-256 y lectura JSON. No se imprimirán secretos, URLs, textos de caso, vectores, prompts, SQL ni excepciones crudas.

Rollback: cambiar sólo `PRODUCT_RECOGNIZER_MODE=shadow`, redeployar producción, verificar factory y salud, y conservar evidencia y artefacto.

## Archivos esperados

Sólo documentos bajo `openspec/changes/promote-production-hybrid-authoritative-policy/`. No se esperan cambios de aplicación.

## Validación propuesta

```sh
openspec validate promote-production-hybrid-authoritative-policy --strict
git diff --check
```

Toda operación sobre Railway producción requiere una autorización posterior, gate por gate, tras revisión de este OpenSpec.

## Limitaciones diferidas

Esta promoción no establece una campaña de observabilidad prolongada, no valida tráfico real y no automatiza transferencia de artefactos. Cualquier cambio técnico surgido de producción requiere un OpenSpec separado.

## Evidencia sanitizada y decisión

La promoción controlada se ejecutó con autorizaciones separadas por gate. El reporte seleccionado se transfirió al volumen persistente independiente de producción mediante escritura temporal, verificación y rename dentro del mismo montaje. El archivo final mantuvo el SHA-256 `cbbc20914b6e4e75ace8915e92e4ff18e358864664ce8818f64db6dcef7f9fc4` antes y después de un redeploy en `shadow`; JSON y el loader existente aceptaron el reporte.

Con el path configurado, producción permaneció en `shadow`, construyó la factory autorizada de forma controlada y respondió `200` en `/health`. La comprobación técnica de dependencias generó un embedding fijo no comercial de dimensión `384` y verificó el short-circuit vectorial con candidatos vacíos, sin consultar catálogo ni escribir en datos de producción.

La activación temporal a `hybrid_authoritative` construyó `HybridAuthoritativeProductRecognizer` y respondió `200` en `/health`, sin Twilio, mensajes reales ni tráfico de negocio. Se validó después el rollback inmediato a `shadow`: la factory efectiva volvió a `ShadowedProductRecognizer`, health permaneció sano y el artefacto persistente conservó el SHA registrado.

Tras una autorización explícita posterior, producción se reactivó a `hybrid_authoritative`. El redeploy final fue exitoso, `/health` respondió `200`, settings reportó el path verificado y la factory efectiva volvió a construir `HybridAuthoritativeProductRecognizer`.

Decisión: al cierre de este change, producción queda activa en `hybrid_authoritative`, con rollback probado y disponible a `shadow`, y con el artefacto y policy path preservados. Esta evidencia no sustituye observación prolongada ni valida tráfico real; cualquier cambio posterior de modo requiere autorización operacional explícita.
