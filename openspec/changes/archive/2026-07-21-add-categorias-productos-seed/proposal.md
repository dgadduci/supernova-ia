## Why

`categorias_productos` is empty on both `supernova` and `supernova_test`. `Producto.id_categoria_producto` (Subphase 1.7) FKs to `categorias_productos.id`, and `Comercio.id_comercio` (via CASCADE) is the per-comercio ownership. Without seed rows, no demo or smoke test can populate the product catalog for a comercio. This change seeds each comercio with a small starter set of categories so the catalog hierarchy has something to attach products to.

## What Changes

- Add `backend/db/seeds/data/categorias_productos.json` with one row per (comercio, category) pair.
- Add `backend/db/seeds/seeds/categorias_productos.py` that loads the JSON into one target database at a time.
- The JSON references each parent comercio by business key (`comercio_cuit`); the script resolves it to id against the live `comercios` table at run time. This keeps the JSON portable across DBs where the same comercio has different ids.
- The script is idempotent on the composite `(id_comercio, descripcion)` pair (the natural business key; the model does not declare a unique constraint over this pair).
- Each row in the JSON supplies an explicit `orden` value (the model has a default of 0, but the seed provides a display order).
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-categorias-productos`: An idempotent seed operation that populates `categorias_productos` from a JSON data file into the selected database, resolving each row's parent reference via the `comercio_cuit` business key at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/categorias_productos.json`, `backend/db/seeds/seeds/categorias_productos.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependency**: requires `comercios` rows to exist in the target DB (already true after the `seeds-comercios` subphase).
