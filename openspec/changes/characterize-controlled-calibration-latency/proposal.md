# Caracterizar la latencia de calibración híbrida controlada

## Objetivo

Caracterizar de forma reproducible y segura la latencia que bloqueó dos calibraciones controladas del reconocimiento híbrido en Railway. El cambio añadirá evidencia agregada por etapa —fuzzy, embedding, búsqueda vectorial y decisión/evaluación— para decidir qué límite técnico investigar después, sin modificar el dataset congelado, el presupuesto de elegibilidad ni la autoridad de Fuzzy.

## Estado y ruta actual

El entorno Railway `calibracion` usa el catálogo dedicado, sus embeddings y el dataset congelado `backend/data/product_recognition_calibration_cases.json`. Dos reportes persistentes ejecutaron 47 casos y 243 políticas; ambos mejoraron `decision_accuracy` de 0.5319 a 0.8936, pero fueron `eligibility.status == "not_eligible"` exclusivamente por `latency_budget_failed`: p95 de 512.1 ms y 527.4 ms frente al presupuesto congelado de 500 ms. Cada corrida informó tres fallos de infraestructura.

El runner actual sólo expone latencia total por caso y agregados p50/p95. Sus errores de embedding/vector se agrupan como fallos técnicos; no deja evidencia agregada para atribuir el p95 a una etapa concreta sin registrar texto de caso o excepciones crudas.

## Alcance

- Añadir instrumentación agregada para fuzzy, embedding, vector search y evaluación/decisión.
- Registrar conteos de intentos, éxitos y fallos técnicos por etapa usando categorías seguras y estables, nunca excepciones crudas.
- Emitir esos agregados dentro del JSON de calibración existente, para conservarlos en el volumen Railway persistente.
- Definir la operación de varias corridas controladas con el mismo dataset, catálogo dedicado y configuración actual, para comparar p50, p95 y máximo por etapa sin tráfico real.
- Mantener `eligibility.status` como único veredicto de política.

## No objetivos

- No cambiar dataset, `latency_budget_ms_p95`, criterios de elegibilidad, política seleccionada ni grid de políticas.
- No cambiar recognizers, candidatos permitidos/restringidos, modelo Ollama, embeddings, vector search, índices, timeouts, Railway, Tailscale, UFW, Docker, variables ni migraciones.
- No volver a indexar catálogo, ejecutar Twilio/WhatsApp, tráfico real ni acceder a clientes, pedidos, sesiones, mensajes o logs de producción.
- No activar `hybrid_authoritative`, configurar `HYBRID_AUTHORITATIVE_POLICY_PATH`, sync, archive, commit, push o deploy.

## Resultados y fallback

| Hecho | Resultado | Acción |
| --- | --- | --- |
| Corrida con agregados completos | Evidencia comparable | Revisar p50/p95/máximo y fallos por etapa |
| Una etapa domina p95 repetidamente | Hipótesis técnica sustentada | Proponer un cambio separado sólo para esa etapa |
| Agregados incompletos o fallo de CLI | Evidencia insuficiente | Mantener `shadow`; no cambiar umbral |
| `eligibility.status != "eligible"` | Reporte no apto como política | Mantener Fuzzy como autoridad |
| p95 sobre 500 ms repetidamente | Requisito actual incumplido | No elevar el umbral en este cambio |

Fuzzy continúa como autoridad segura en `shadow`. La instrumentación no controla transacciones: la calibración conserva sus lecturas actuales y la escritura atómica del reporte es sólo evidencia.

## Seguridad, persistencia y reversibilidad

El reporte podrá incluir únicamente `count`, `success_count`, `failure_count`, `p50_ms`, `p95_ms` y `max_ms` por etapa, más categorías técnicas seguras. Queda prohibido serializar o imprimir `input_text`, vectores, prompts, resultados por caso, URLs, credenciales, SQL, trazas o mensajes crudos. No se usará `--diagnose`.

Los campos son observabilidad aditiva de reportes existentes. Los reportes previos se conservan; ninguno con `not_eligible` se instala como política runtime.

## Archivos esperados

- `backend/services/product_recognition_calibration_runner.py`
- Test focal existente del runner
- `backend/cli/calibrate_product_recognizer.py`, sólo si hiciera falta para exponer salida agregada segura
- `openspec/changes/characterize-controlled-calibration-latency/`

## Validación propuesta

El usuario ejecutará localmente y aportará la salida completa:

```sh
PYTHONPATH=. venv/bin/python -m pytest -q backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_runner.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_3.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_4_11_3.py
openspec validate characterize-controlled-calibration-latency --strict
git diff --check
```

La operación Railway requerirá una aprobación posterior e independiente. Esta etapa no concluye una causa ni implementa su arreglo: cualquier corrección técnica o cambio de presupuesto necesitará su propio OpenSpec y aprobación.
