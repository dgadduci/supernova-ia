## Decisión

Esta etapa es una puerta de evidencia entre `shadow` y una futura promoción:

```text
fuzzy estable -> shadow controlado -> calibración elegible
  -> artefacto persistente comprobado -> (cambio posterior) hybrid_authoritative
```

La calibración no cambia autoridad. `shadow` continúa ejecutando fuzzy como
resultado de negocio; el CLI se invoca fuera del flujo HTTP/Twilio con el
dataset congelado y sólo consulta el catálogo/vector existente.

## Secuencia controlada

1. Confirmar que Railway permanece en `shadow`, que el transporte embed ya
   pasa sus gates y que el destino contiene sólo el catálogo controlado que
   referencia el dataset.
2. Ejecutar el CLI existente con el dataset completo y una salida temporal
   segura para revisión; no se considera política runtime.
3. Revisar el JSON: versión y fingerprint esperados, número de casos/políticas,
   `eligibility.status`, razones, métricas agregadas e integridad de
   `selected_policy`. El status del propio reporte es la autoridad: exit 0 no
   equivale a elegibilidad.
4. Si y sólo si es `eligible`, comprobar el mecanismo de persistencia Railway
   antes de promover el archivo: montaje, permisos, escritura atómica,
   lectura por el usuario de runtime y supervivencia al reinicio/redeploy
   acordado. Registrar la ruta real y hash sólo como evidencia segura.
5. Entregar el reporte y evidencia para revisión. No se cambia ningún
   environment variable ni se instancia el modo autoritativo.

## Reglas de resultado

| Hecho observado | Interpretación | Comportamiento |
| --- | --- | --- |
| CLI exit 0 y `eligible` | Calibración apta como candidata | Puede avanzar a persistencia comprobada, nunca a activación automática |
| CLI exit 0 y `not_eligible`/`pending` | Reporte válido pero no apto | Retener sólo como evidencia; seguir en shadow |
| CLI non-zero o reporte ausente/malformado | Calibración no fiable | No conservar como política ni cambiar configuración |
| Reporte eligible sin montaje persistente | Evidencia insuficiente para runtime | No definir `HYBRID_AUTHORITATIVE_POLICY_PATH` |
| Montaje persistente, reporte ilegible o alterado | Artefacto no confiable | No promover; conservar modo actual |

Los errores técnicos jamás se reinterpretan como resultados de reconocimiento
ni habilitan una política. La ruta `hybrid_authoritative` sigue fallando
cerrado mediante su loader existente si el archivo falta, está malformado o no
es elegible.

## Contrato de almacenamiento

No hay ruta persistente detectada en `Dockerfile`, `railway.toml` ni el
runbook actual. Por tanto esta especificación no nombra una ruta como existente.
El contrato que se aprobará operativamente es:

- el mecanismo pertenece al servicio Railway y persiste fuera de `/tmp` y de
  la capa efímera de imagen;
- la ruta concreta es confirmada por el operador antes de ejecutar la copia;
- el reporte se escribe mediante el escritor atómico existente y es sólo
  legible por el runtime necesario;
- se registra un hash SHA-256 y se vuelve a leer/parsear el JSON después de la
  frontera de persistencia acordada;
- el diagnóstico por caso no se promueve al montaje de política;
- una futura configuración apunta exactamente a ese reporte y permanece
  reversible al volver a `shadow`/`fuzzy`.

No se crean volúmenes, variables, rutas, scripts ni políticas durante este
cambio. Si Railway no ofrece un montaje verificable, el resultado correcto es
deferir la promoción.

## Ownership de transacciones

El CLI existente crea/cierra su propia sesión. Esta etapa exige un destino
read-only y no autoriza ninguna mutación de catálogo, datos de negocio o
transacciones caller-owned. La persistencia del JSON es filesystem del
artefacto, no una transacción de PostgreSQL y no debe ampliar la sesión del
CLI.

## Validación y revisión

La revisión posterior exigirá, como mínimo:

1. salida completa del CLI local con `venv` y evidencia Railway sanitizada;
2. inspección de `eligibility.status`, `selected_policy`, fingerprint y hash;
3. prueba de persistencia/lectura del archivo en el montaje confirmado;
4. `openspec validate calibrate-railway-hybrid-recognition-policy --strict` y
   `git diff --check` con salida completa;
5. confirmación de que no se alteraron `PRODUCT_RECOGNIZER_MODE`,
   `HYBRID_AUTHORITATIVE_POLICY_PATH`, Twilio ni datos de negocio.

No se requieren tests o Ruff/compileall porque este cambio crea sólo OpenSpec.
Si una fase posterior modifica código, configuración o tests, definirá sus
validaciones focalizadas y el usuario ejecutará cualquier comando `venv`.
