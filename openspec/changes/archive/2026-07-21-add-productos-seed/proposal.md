## Why

`productos` is empty on both `supernova` and `supernova_test`. `producto_presentaciones.id_producto` (Subphase 1.7) and `producto_precios.id_producto_presentacion` (Subphase 1.8) FKs all eventually flow back to `productos.id`. Without seed rows, no demo or smoke test can populate the catalog, attach presentations to products, or assign prices. This change seeds a starter catalog for each comercio so the downstream hierarchy has rows to operate on.

## What Changes

- Add `backend/db/seeds/data/productos.json` with one row per (comercio, category, product) triple, generated from `backend/db/seeds/data/prod_json.json` cross-referenced with each comercio's categories.
- Add `backend/db/seeds/seeds/productos.py` that loads the JSON into one target database at a time.
- The product name/description source of truth is `prod_json.json`; `productos.json` is a generated cross-reference of that catalog with each comercio's `categorias_productos`. Updating the catalog (e.g., adding a new pizza flavor) is a single edit to `prod_json.json` followed by regenerating `productos.json` and running the seed.
- The JSON references each parent comercio by business key (`comercio_cuit`) and each category by name. The script resolves both to ids at run time. The category lookup is case-insensitive (lower-folding both sides) because `prod_json.json` uses uppercase category names (`PIZZAS`) while the existing `categorias_productos` table stores them in title case (`Pizzas`).
- The script is idempotent on the composite `(id_categoria_producto, nombre)` pair (the model's `UniqueConstraint categoria_producto_nombre_unico`).
- The presentation references in the user's request are **descriptive context only** — `Producto` has no direct FK to `Presentacion`; the join happens via `producto_presentaciones`, which is a separate seed target. This seed populates only the `productos` table.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-productos`: An idempotent seed operation that populates `productos` from a JSON data file into the selected database, resolving each row's parent comercio and category references via business keys at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/productos.json`, `backend/db/seeds/seeds/productos.py`.
- **Read-only reference**: `backend/db/seeds/data/prod_json.json` (product catalog, not modified by this change).
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependencies**: requires `comercios` (Subphase `seeds-comercios`) and `categorias_productos` (Subphase `seeds-categorias-productos`) rows to exist in the target DB.
- **Out of scope**: the `producto_presentaciones` and `producto_precios` join tables. These require separate seeds that consume the products and presentations rows this seed creates (or that come after it).
