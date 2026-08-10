## Decisión

Producción no hereda estado de `calibracion`. La promoción parte de `shadow` y sigue gates independientes de persistencia, artefacto, dependencias, carga y rollback.

No se configura `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` hasta que el artefacto existe en una ruta persistente de producción, mantiene su SHA-256 tras el redeploy acordado y es aceptado por el loader existente. La ruta se configura primero mientras producción permanece en `shadow`.

## Flujo

```text
evidencia elegible de calibracion
  -> descubrir volumen/ruta real de producción
  -> verificar o transferir artefacto bajo autorización
  -> hash + JSON antes/después de redeploy en shadow
  -> policy path en shadow + loader/factory
  -> activar hybrid_authoritative
  -> health + observación autorizada
  -> rollback a shadow si cualquier gate falla
```

## Validación controlada

Las comprobaciones de loader/factory no envían mensajes, no invocan Twilio y no ejecutan conversación E2E. Health prueba liveness, no comportamiento de negocio. No se considera una respuesta 200 como suficiente sin el gate de loader/factory y el artefacto verificado.

## Rollback

El rollback no borra la política ni las evidencias. Restituye solamente `PRODUCT_RECOGNIZER_MODE=shadow`, aplica redeploy y confirma que Fuzzy es otra vez la autoridad.
