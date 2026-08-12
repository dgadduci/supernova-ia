# Verificar estado operativo post-4.12B antes de sincronizar

## Why

La evidencia histórica de las subfases 4.12B y de observabilidad no demuestra
el estado actualmente desplegado. Antes de cualquier decisión posterior se
necesita una verificación mínima y de sólo lectura, con target explícito y sin
exponer secretos ni generar tráfico.

## What Changes

- Definir gates read-only para identidad de target y revisión desplegada,
  configuración y política, carga/salud y observabilidad acotada.
- Registrar evidencia sanitizada y criterios explícitos de detención.
- Mantener cualquier cambio de modo, redeploy o rollback fuera de alcance y
  sujeto a una autorización posterior separada.

## Objetivo

Definir una verificación operacional mínima, por gates y reversible, del estado desplegado de NovaOrders después de los commits locales de la Subfase 4.12B (`84f414c`, `13a6b71`, `0615a22`) y antes de cualquier sincronización, deploy o cambio de entorno. La verificación obtiene sólo evidencia sanitizada del SHA/revisión desplegada, modo configurado y efectivo, ruta/persistencia de la política, health/factory y observabilidad acotada.

## Estado y ruta actual verificados

La rama local contiene los tres commits anteriores y no tiene cambios de trabajo al crear este change. No existe un change OpenSpec activo. La Subfase 4.12B dejó un único límite compartido de selección en `get_product_recognizer(load_settings())`: `fuzzy`, `shadow` y `hybrid_authoritative`; un modo inválido resuelve con seguridad a `fuzzy`. En modo autoritativo, `HybridAuthoritativePolicySource` lee el JSON indicado por `HYBRID_AUTHORITATIVE_POLICY_PATH` y falla cerrado si falta, no es JSON, no es elegible o no cumple el contrato de política. `/health` sólo prueba liveness. Las observaciones de reconocimiento se emiten como `shadow_product_recognition`; la CLI existente de logs Railway sólo permite consultas acotadas de eventos operacionales versionados, no las sustituye ni revela líneas crudas.

El change archivado `promote-production-hybrid-authoritative-policy` registra una activación histórica de producción en `hybrid_authoritative`. Es evidencia histórica, no estado actual: esta fase no presupone ni configura ese modo.

## Alcance

- Preparar gates read-only que, tras aprobación operacional explícita, obtengan evidencia de la revisión/SHA desplegada y la identidad explícita del target Railway.
- Verificar sin secretos el modo configurado y efectivo, la presencia y elegibilidad del artefacto de política, su ruta persistente y su hash.
- Confirmar de forma controlada settings, loader, factory y health sin Twilio, webhook, mensajes, catálogo, sesiones ni datos de clientes.
- Consultar una ventana breve y acotada de observabilidad existente; ausencia de eventos no se interpreta como éxito ni como estado de negocio.
- Definir el rollback a `shadow`, la evidencia mínima y los criterios de stop.

## No objetivos

No sync/push, deploy, Railway mutation, cambio de variables, redeploy, Twilio/WhatsApp, tráfico real o sintético, datos de clientes, recalibración, código, tests, embeddings, catálogo, modelos, índices, migraciones, LangGraph ni endpoints nuevos. Tampoco se modifica ni transfiere el artefacto de política, ni se declara que producción está en una revisión o modo sin evidencia fresca.

## Gates, evidencia y stop

| Gate | Evidencia sanitizada requerida | Stop / acción |
| --- | --- | --- |
| G0: autorización | Aprobación explícita para el gate read-only concreto y target Railway identificado | No ejecutar operación externa |
| G1: identidad | Proyecto, entorno y servicio explícitos; revisión/SHA desplegada, sin variables ni URLs | Si no coincide o no puede obtenerse, no sync ni cambio de modo |
| G2: configuración | `configured_mode` y `effective_mode`; categoría segura si difieren | Si es inválido, efectivo debe ser `fuzzy`; no corregir variables |
| G3: política | Ruta no secreta, montaje persistente, JSON elegible y SHA-256; sin contenido del reporte | Si falta, cambia o el loader rechaza, no activar ni tocar la política |
| G4: carga/salud | Clase efectiva de factory, resultado settings/loader seguro y `/health` 200 | Si falla, detener; no usar health como prueba de negocio |
| G5: observación | Ventana y límite explícitos; conteos/categorías allowlisted, sin líneas crudas | Si hay fallback técnico inesperado, error o datos no sanitizables, detener y preservar evidencia |
| G6: decisión | Registro de evidencia y decisión humana explícita para cualquier paso posterior | Mantener estado; ninguna mutación queda autorizada por este change |

Fuzzy es el fallback seguro. `unknown`, `ambiguous`, baja confianza y vector vacío son resultados de negocio válidos del híbrido y no justifican rollback por sí solos. Fallo de configuración, artefacto, loader, factory, deploy o salud impide avanzar; sólo tras una aprobación separada puede aplicarse el rollback operativo a `PRODUCT_RECOGNIZER_MODE=shadow`.

## Transacciones, observabilidad y reversibilidad

Esta fase no abre ni muta transacciones, no escribe PostgreSQL y no cambia ownership de commit/rollback. Toda evidencia se reduce a identificadores de target, SHA/revisión, hashes, nombres de clase, estado HTTP, conteos y categorías allowlisted. Se excluyen secretos, URLs, cuerpos, E.164, payloads, prompts, vectores, SQL, excepciones crudas y líneas Railway sin parsear.

No hay mutación que revertir durante la preparación o gates read-only. El plan de contingencia posterior, sujeto a autorización por gate, es cambiar solamente el modo a `shadow`, redeployar el target autorizado y volver a verificar factory, health y hash del artefacto; no se borra evidencia ni se reescribe la política.

## Archivos esperados

Sólo `openspec/changes/verify-post-4-12b-production-state/`: propuesta, diseño, delta de capability y tareas. No se esperan cambios de aplicación.

## Validación

El usuario deberá ejecutar y aportar la salida completa desde su terminal local:

```sh
openspec validate verify-post-4-12b-production-state --strict
git diff --check
```

Después de aprobación de este OpenSpec, cada gate Railway requerirá una autorización operacional nueva y explícita antes de invocarlo.

## Limitaciones diferidas

Esta fase no demuestra tráfico real, entrega de proveedores, precisión, latencia sostenida ni salud de dependencias bajo carga. Tampoco verifica que los commits locales estén desplegados hasta que G1 autorizado lo pruebe. Cualquier sync, deploy, modificación de configuración, rollback, corrección técnica u observación prolongada exige una decisión y autorización separadas.
