# Promover una política híbrida autoritativa en Railway

## Objetivo

Promover de forma controlada y reversible el reconocimiento de producto de `shadow` a `hybrid_authoritative` únicamente en el entorno Railway `calibracion`, usando un reporte elegible, persistente y verificable del dataset congelado. La promoción no habilita tráfico real, Twilio ni producción.

## Evidencia disponible

Los artefactos persistentes bajo `/data/novaorders-policy` de las corridas instrumentadas 1–3 fueron `eligibility.status == "eligible"`. Sus p95 totales fueron 451.1 ms, 439.9 ms y 391.9 ms, bajo el presupuesto congelado de 500 ms. El loader existente `HybridAuthoritativePolicySource` falla cerrado si el archivo no existe/no es JSON, no lleva `selected_policy` exacta o no declara `eligibility.status == "eligible"`.

## Alcance

- Seleccionar un único reporte elegible de las tres corridas sólo después de confirmar: JSON legible, `selected_policy` idéntica entre corridas o diferencia revisada, fingerprint/version del dataset coherente y hash SHA-256 registrado.
- Verificar que el reporte seleccionado en `/data/novaorders-policy` sobrevive un redeploy de `calibracion` mientras el modo sigue en `shadow`.
- Configurar primero `HYBRID_AUTHORITATIVE_POLICY_PATH` en `calibracion`; sólo después, y con verificación de lectura satisfactoria, configurar `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative`.
- Comprobar de manera controlada que settings, loader y factory construyen el reconocedor autoritativo con el artefacto elegido.
- Definir reversión inmediata a `shadow` sin borrar los reportes de evidencia.

## No objetivos

- No modificar código, tests, dataset, política, umbrales, modelo Ollama, embeddings, catálogo, índices, vector search, timeouts, Tailscale, UFW, Railway de producción, Docker ni migraciones.
- No crear una política nueva ni editar el JSON elegido.
- No Twilio/WhatsApp E2E, mensajes reales, tráfico de clientes, pedidos, sesiones ni datos de producción.
- No promover producción, sync, archive, commit ni push como parte de esta operación.

## Secuencia y gates

| Gate | Evidencia requerida | Si falla |
| --- | --- | --- |
| Selección | JSON elegible, hash, versión/fingerprint y política revisados | Mantener `shadow` |
| Persistencia | Mismo SHA-256 y JSON legible antes/después de redeploy en `shadow` | Mantener `shadow` |
| Path | `HYBRID_AUTHORITATIVE_POLICY_PATH` apunta exactamente al archivo verificado | Mantener `shadow` |
| Carga | Settings + loader + factory construyen sin excepción | No cambiar modo |
| Activación | Sólo `calibracion`, deploy sano y validación controlada | Revertir a `shadow` |
| Reversión | `PRODUCT_RECOGNIZER_MODE=shadow`, redeploy sano | Bloquear toda expansión |

El fallback seguro es Fuzzy: en `hybrid_authoritative`, fallos técnicos de embedding/vector conservan el fallback interno a Fuzzy; si configuración/artefacto/carga falla, el modo se devuelve a `shadow`.

## Persistencia, transacciones y seguridad

El reporte elegido ya es un artefacto JSON atómico en el volumen persistente. No se copia, reescribe ni elimina durante la promoción. Se lee y hashea; no se imprime contenido de casos, vectores, URLs, credenciales ni excepciones crudas. La operación no abre ni muta transacciones de PostgreSQL.

## Archivos esperados

Sólo documentos bajo `openspec/changes/promote-railway-hybrid-authoritative-policy/`. La promoción usa settings, loader y factory existentes; no espera cambios de aplicación.

## Validación propuesta

Antes de la operación Railway, el usuario aportará:

```sh
openspec validate promote-railway-hybrid-authoritative-policy --strict
git diff --check
```

La ejecución operacional requerirá aprobación separada después de revisar este OpenSpec. La evidencia de cada gate se compartirá sanitizada y se revisará antes del siguiente gate.

## Limitaciones diferidas

La promoción no demuestra comportamiento sobre tráfico real ni reemplaza observación prolongada. Producción, cambio de umbral, cambios de rendimiento, persistencia alternativa y archive/sync de OpenSpec requieren cambios y aprobaciones independientes.

## Evidencia sanitizada y decisión

Se seleccionó `calibration-latency-2026-08-09-run3.json` como candidato elegible: su SHA-256 fue `cbbc20914b6e4e75ace8915e92e4ff18e358864664ce8818f64db6dcef7f9fc4`, conservó JSON válido y fue aceptado por el loader existente. La misma política seleccionada estuvo presente en las tres corridas elegibles.

En `calibracion`, el artefacto conservó el mismo SHA tras un redeploy en `shadow`. Luego se configuró el path, se verificaron settings, loader y factory, y se activó `hybrid_authoritative` de forma controlada. `/health` respondió `200` y la factory efectiva construyó `HybridAuthoritativeProductRecognizer`, sin Twilio, mensajes reales ni tráfico de negocio.

El rollback a `shadow` fue probado y preservó el artefacto; la posterior reactivación de `calibracion` se realizó bajo autorización. Producción no formó parte de este change: su promoción se documenta separadamente en `promote-production-hybrid-authoritative-policy`. La decisión de esta fase fue no elevar el presupuesto de latencia ni modificar código, dataset o política.
