## Decisión de aislamiento

El catálogo vive sólo en una base Railway dedicada, vacía y confirmada; no
comparte base con el fixture piloto. Así ambos seeders conservan su ownership.

```text
Railway DB dedicada vacía -> verify-only -> apply explícito
  -> verify-only / manifiesto exacto -> calibración en cambio posterior
```

## Inventario exacto

El fixture se deriva de la superficie declarada del manifiesto pero se
materializa como datos estáticos versionados y revisables. Cubre literalmente
todas las asociaciones, incluidos Margherita, Fugazza, Roquefort, Hawaiana,
Especial de la Casa, Coca-Cola, Sprite, Vino tinto Malbec y postres requeridos.
No reproduce PKs históricas: el adaptador resuelve IDs runtime.

Una auditoría falla si no existe coincidencia exacta/unívoca por token. No hay
sinónimos, marcas sustitutas ni adaptación de nombres en runtime.

## CLI y guard

`python -m backend.cli.seed_dedicated_railway_calibration_catalog` usa
`--verify-only` por defecto y `--apply` como única mutación. Requiere un
marcador no secreto de destino dedicado, nunca comparación de URL/host. Tras
un flush permitido verifica cobertura, comercio, forma y conteos; exacto es
`ready`, cualquier diferencia es `conflict`.

## Validación

Pruebas focalizadas cubren no-op, guard de destino, namespace vacío, primer
apply, rerun, conflicto sin overwrite, rollback, cobertura de manifiesto,
resolución completa y ausencia de integración WhatsApp/Twilio. No se opera
Railway durante implementación.
