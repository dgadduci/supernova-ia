## Decisión

La calibración conservará su comportamiento de decisión y elegibilidad, pero medirá internamente cuatro etapas: Fuzzy, embedding, vector search y evaluación/decisión.

La unidad por caso sólo existirá en memoria durante la corrida. El JSON final recibirá un bloque aditivo `latency_breakdown` con estadísticas agregadas por etapa y categorías seguras de fallo. El bloque no contendrá IDs de caso, texto, vectores, resultados de búsqueda ni mensajes de excepción.

## Flujo

```text
dataset congelado + catálogo dedicado
  -> fuzzy (tiempo agregado)
  -> embedding (tiempo agregado / fallo seguro)
  -> vector search (tiempo agregado / fallo seguro)
  -> evaluación (tiempo agregado)
  -> reporte JSON con eligibility actual + latency_breakdown
```

La suma de etapas es evidencia diagnóstica. La latencia total existente continúa siendo la métrica que consume la elegibilidad; no se redefine p50, p95 ni el presupuesto de 500 ms.

## Contrato de fallos

| Condición | Categoría segura | Efecto |
| --- | --- | --- |
| Fuzzy lanza un fallo capturable existente | `fuzzy_failure` | Conserva el comportamiento actual y contabiliza la etapa |
| Embedding falla | `embedding_failure` | No inventa vector; contabiliza embedding |
| Vector falla | `vector_failure` | No ensancha candidatos; contabiliza vector |
| No hay casos híbridos evaluables | Resultado técnico existente | No emite política; no cambia umbral |

No se incluye `type(error)`, texto de excepción ni datos de proveedor. La instrumentación debe conservar categorías existentes, no crear un fallback paralelo.

## Repetición controlada

Tras implementación y revisión, el operador podrá ejecutar varias corridas sin `--diagnose`, cada una a un archivo nuevo dentro de `/data/novaorders-policy`. La comparación revisará sólo agregados y `eligibility`. Todas las corridas permanecen en `shadow`; ningún reporte sustituye ni se convierte en política.

## Transacciones y reversibilidad

El runner no adquiere propiedad de transacciones caller-owned. No se agregan consultas mutantes ni escrituras de base. La única escritura permitida es el reporte JSON atómico existente. Retirar instrumentación futura no elimina evidencia persistida ni modifica el modo de reconocimiento.
