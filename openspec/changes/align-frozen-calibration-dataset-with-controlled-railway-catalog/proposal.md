# Alinear el dataset congelado de calibración con el catálogo controlado Railway

## Objetivo

Eliminar la dependencia incorrecta del dataset congelado de calibración sobre
IDs físicos globales de `producto_presentacion`, conservando sus casos,
textos, expectativas y límites de candidatos, para que pueda ejecutarse de
forma read-only contra el catálogo fixture controlado de Railway.

El resultado será un artefacto de identidad versionado que asocia cada
referencia lógica del dataset con una asociación de producto-presentación del
catálogo fixture mediante identidad de negocio estable, no por su PK física.
El runner recibirá sólo IDs resueltos en memoria para la ejecución actual.

## Evidencia y ruta actual

La calibración Railway cargó dataset, settings y sesión, pero falló antes de
evaluar casos con:

`SeedReferenceError(case_id="c1-ambiguous-postre", offending_value=69,
expected_commerce=1)`.

El dataset contiene límites dinámicos fijos como `69..72` para comercio 1.
El fixture Railway define 59 `ProductoPresentacion` por comercio y sólo fija
forma/identidad de catálogo; no promete esos IDs globales. El runner actual
valida cada `allowed_candidate_ids`, `restricted_candidate_ids` y `seed_refs`
contra la PK física y el comercio de la base, por lo que falla cerrado.

## Alcance

- Definir una representación versionada de identidad lógica para cada
  referencia dinámica del dataset y una tabla de correspondencia hacia el
  catálogo fixture controlado.
- Resolver esa correspondencia al inicio de la calibración mediante claves
  estables del fixture (comercio fixture, categoría, producto y presentación),
  comprobar unívocamente comercio y disponibilidad, y materializar en memoria
  los IDs físicos para el runner existente.
- Mantener el dataset fuente congelado sin reescribir casos, textos, resultados
  esperados ni listas de candidatos para mejorar métricas.
- Fallar cerrado antes de embedding/vector si falta, sobra, es ambigua o cruza
  un comercio una correspondencia.
- Añadir pruebas focalizadas de resolución, aislamiento, inmutabilidad de
  fuente y compatibilidad del runner/CLI.

La cobertura insuficiente del fixture es un bloqueo deliberado: si una identidad
histórica no existe exactamente en el fixture, la calibración falla cerrado y el
cambio de fixture requerido debe aprobarse como cambio separado. No se permite
resolver la falta mediante sustitución semántica, alias aproximado o cruce de
categoría.


- No sembrar ni modificar datos Railway en este cambio; el seeder existente no
  se ejecuta con `--apply`.
- No cambiar fuzzy, shadow, hybrid, thresholds, modelos, Ollama, Tailscale,
  Twilio, tráfico real, migraciones ni el catálogo fixture de WhatsApp.
- No cambiar el significado del dataset, ocultar casos fallidos, relajar
  candidate boundaries ni reutilizar una PK de otro comercio.
- No ejecutar la calibración operativa, crear políticas persistentes, activar
  `hybrid_authoritative`, deploy, sync, archive, commit o push.

## Límite compartido y fallback

| Condición | Resultado | Acción |
| --- | --- | --- |
| Cada referencia lógica resuelve una única asociación activa del fixture en su comercio | Dataset materializado en memoria | Ejecutar el runner existente sin mutación |
| Referencia ausente, ambigua, inactiva o de comercio distinto | Error tipado de alineación | Detener antes de embeddings; mantener shadow |
| Dataset sin casos dinámicos seleccionados | No se requiere adaptación | Mantener comportamiento actual |
| Falla técnica posterior del runner | Fuzzy sigue siendo autoridad | Aplicar el fallback existente; no alterar límites |

El adaptador no posee transacciones: su consulta es read-only y no llama
`commit`, `rollback`, `begin`, `flush` ni `close`. La sesión sigue siendo
propiedad del CLI actual.

## Observabilidad y seguridad

Los errores seguros pueden informar `case_id`, token lógico, comercio fixture,
tipo de conflicto y conteos. No incluyen texto de entrada, datos de clientes,
precios, URLs, credenciales, vectores, SQL ni excepciones crudas. El reporte
de calibración conserva su contrato de redacción actual.

## Archivos esperados

- Un módulo de manifiesto/resolución bajo `backend/services/`.
- Ajuste mínimo del CLI o runner para invocar el adaptador únicamente para el
  catálogo fixture explícitamente seleccionado.
- Tests focalizados bajo `backend/tests/`.
- Este OpenSpec y su delta de capability.

## Validación prevista

El usuario ejecutará localmente las validaciones con `venv` y aportará salida
completa. Se requerirán tests de adaptador/runner/CLI, Ruff y compileall de
los archivos tocados, además de:

```sh
openspec validate align-frozen-calibration-dataset-with-controlled-railway-catalog --strict
git diff --check
```

La futura operación Railway deberá comenzar por verificación read-only del
fixture, continuar con una calibración sin `--diagnose`, y revisar
`eligibility.status`; queda fuera de este cambio de diseño.

## Reversibilidad y límites diferidos

El adaptador no persiste datos. Se revierte retirando su uso/configuración en
un cambio posterior; no exige downgrade de base. La creación de un nuevo
fixture de catálogo, cambios de contenido del dataset o promoción de hybrid
son decisiones separadas y explícitas.
