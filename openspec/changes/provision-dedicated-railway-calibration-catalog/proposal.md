# Provisionar catálogo Railway dedicado para calibración congelada

## Objetivo

Proveer un catálogo sintético, determinista y exclusivo para ejecutar el
dataset congelado `backend/data/product_recognition_calibration_cases.json`
sin reinterpretar identidades de negocio. El catálogo residirá en un destino
Railway dedicado y vacío, separado del fixture/piloto WhatsApp, y cubrirá cada
producto, categoría y presentación del manifiesto de calibración.

## Ruta actual y evidencia

El adaptador de identidad traduce PKs runtime sólo con identidad exacta. El
fixture WhatsApp contiene una superficie de productos distinta y falla cerrado
con `MissingRuntimeIdentityError`; no permite sustituir pizza por bebida ni
aproximar productos. Su seeder es propietario de tres comercios y exige un
namespace vacío/exacto, por lo que este catálogo no puede coexistir ni
ampliarlo informalmente.

## Alcance

- Definir un fixture de calibración aislado, con un comercio sintético estable
  y un inventario que cubra exactamente todas las identidades del manifiesto.
- Añadir un CLI interno verify-only por defecto y `--apply` explícito, limitado
  a una base Railway dedicada/vacía confirmada por el operador.
- Proveer transacción única, rechazo de conflicto, rerun exacto no mutante,
  salida sanitizada y verificación completa de forma/cobertura.
- Probar que el adaptador resuelve toda identidad del fixture sin alias,
  aproximaciones ni cruces de categoría.

## No objetivos

- No modificar el seeder ni los comercios del piloto WhatsApp.
- No operar sobre una base con piloto, clientes, pedidos, sesiones, mensajes o
  datos no controlados.
- No modificar el dataset congelado, recognizers, modelos, Ollama, Tailscale,
  Twilio, migraciones ni configuración hybrid.
- No ejecutar calibración, deploy, sync, archive, commit o push en este cambio.

## Destino, transacciones y fallback

Antes de `--apply`, el operador confirma que el destino Railway dedicado está
vacío y tiene un marcador no secreto propio. El CLI no recibe ni imprime URLs.
Si el destino no es dedicado, no está vacío, falta esquema o diverge, devuelve
`conflict`/error seguro sin insertar, reparar, borrar ni mezclar filas.

El CLI posee una transacción: helpers no hacen `commit`, `rollback`, `begin`,
`flush` ni `close`; puede hacer un único flush de verificación, commit sólo
tras éxito exacto y rollback ante fallo.

| Condición | Resultado | Acción |
| --- | --- | --- |
| Destino vacío y `--apply` | Fixture exacto provisionado | Commit único |
| Fixture exacto existente | `ready` | No mutar |
| Verify-only sobre destino vacío | `not_ready` | No mutar |
| Piloto, datos previos o divergencia | `conflict` | No mutar |
| Identidad del manifiesto no cubierta | Error de especificación | No calibrar |

## Identidad y observabilidad

El inventario usa coincidencias literales de comercio, categoría, producto y
presentación. Los IDs físicos son irrelevantes: el adaptador los resuelve. La
salida sólo informa modo, estado, conteos, slug fixture, versión/fingerprint e
IDs seguros; no expone URL, credenciales, clientes, mensajes, vectores, precios
individuales ni excepciones crudas.

## Archivos esperados

- Datos/servicio estáticos bajo `backend/services/` o `backend/db/seeds/`.
- `backend/cli/seed_dedicated_railway_calibration_catalog.py`.
- Tests focalizados bajo `backend/tests/`.
- Este OpenSpec y su delta de capability.

## Validación prevista

El usuario ejecutará pytest focal, Ruff y compileall con `venv` localmente y
aportará salida completa. También:

```sh
openspec validate provision-dedicated-railway-calibration-catalog --strict
git diff --check
```

Después de aprobación/deploy, la operación será verify-only, confirmación de
destino dedicado, apply único, verify-only y resolución read-only del
manifiesto. Calibración/política/hybrid quedan en cambios posteriores.

## Reversibilidad

El CLI no borra datos. Sustituir/restaurar el destino dedicado es una decisión
de infraestructura explícita y separada.
