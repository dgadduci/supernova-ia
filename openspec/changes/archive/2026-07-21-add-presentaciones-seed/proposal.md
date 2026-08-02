## Why

`presentaciones` is empty on both `supernova` and `supernova_test`. `producto_presentaciones.id_presentacion` (Subphase 1.7) FKs to `presentaciones.id`, and `Comercio.id_comercio` (via CASCADE) is the per-comercio ownership. Without seed rows, no demo or smoke test can attach presentations to products for a given comercio. This change seeds each comercio with a starter set of presentations so the per-comercio presentation catalog has something to attach to.

## What Changes

- Add `backend/db/seeds/data/presentaciones.json` with one row per (comercio, presentation) pair.
- Add `backend/db/seeds/seeds/presentaciones.py` that loads the JSON into one target database at a time.
- The JSON references each parent comercio by business key (`comercio_cuit`); the script resolves it to id against the live `comercios` table at run time. This keeps the JSON portable across DBs where the same comercio has different ids.
- The script is idempotent on the composite `(id_comercio, codigo)` pair (matches the model's `UniqueConstraint comercio_presentacion_codigo_unico`).
- Each row supplies `codigo`, `descripcion`, `activo`, and `orden`.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-presentaciones`: An idempotent seed operation that populates `presentaciones` from a JSON data file into the selected database, resolving each row's parent reference via the `comercio_cuit` business key at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/presentaciones.json`, `backend/db/seeds/seeds/presentaciones.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependency**: requires `comercios` rows to exist in the target DB (already true after the `seeds-comercios` subphase).
