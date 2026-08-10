## Decisión

La promoción se realiza sólo sobre `calibracion`, en dos cambios de configuración separados:

1. Registrar `HYBRID_AUTHORITATIVE_POLICY_PATH` mientras `PRODUCT_RECOGNIZER_MODE=shadow`; verificar persistencia y carga.
2. Cambiar el modo a `hybrid_authoritative` sólo tras evidencia de que el loader existente acepta el artefacto.

No se crean rutas ni políticas: la ruta exacta se obtiene del archivo elegible que sobreviva el redeploy. El reporte se selecciona por evidencia, no por nombre: JSON válido, estado elegible, huellas coherentes y política revisada. Si los tres reportes tienen la misma política, podrá preferirse el de menor p95, documentando hash y nombre sin exponer contenido sensible.

## Flujo

```text
tres reportes eligible persistentes
  -> selección + SHA-256 + lectura JSON
  -> redeploy en shadow + relectura del mismo SHA-256
  -> configurar sólo policy path en shadow
  -> settings + loader + factory controlados
  -> cambiar modo a hybrid_authoritative en calibracion
  -> deploy sano + smoke controlado sin Twilio
  -> observar o revertir a shadow
```

## Contrato de carga

El loader existente exige `selected_policy` con exactamente seis campos y `eligibility.status == "eligible"`. La factory carga la política cuando el modo efectivo es `hybrid_authoritative`. Un archivo faltante, ilegible, alterado o inelegible es un rechazo seguro: no se improvisa una política ni se continúa con la activación.

## Validación controlada

La comprobación de carga instanciará settings, `HybridAuthoritativePolicySource.load` y la factory sólo en el entorno de calibración. No envía texto de usuario, no ejecuta Twilio y no requiere una conversación E2E. La comprobación posterior al deploy verifica salud del servicio y la misma carga segura; no interpreta `/health` como prueba de reconocimiento de negocio.

## Rollback

Ante cualquier fallo de deploy, loader, factory, lectura del artefacto o comportamiento técnico no esperado:

1. Volver `PRODUCT_RECOGNIZER_MODE=shadow`.
2. Redeploy sólo `calibracion`.
3. Confirmar servicio sano y que Fuzzy vuelve a ser la única autoridad.
4. Conservar reportes, hash y evidencia de falla; no borrar ni sustituir el artefacto.

No se toca producción ni se requiere una reversión de base de datos.
