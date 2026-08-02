## Why

`producto_presentaciones` is empty on both `supernova` and `supernova_test`. `producto_precios.id_producto_presentacion` (Subphase 1.8) FKs to `producto_presentaciones.id`, so the price layer cannot attach until each product is paired with one or more presentations. This change seeds the product ↔ presentation join using a per-category presentation policy, so every product gets the presentation(s) appropriate to its category within the comercio that owns it.

## What Changes

- Add `backend/db/seeds/data/producto_presentaciones.json` with one row per (comercio, category, product, presentation) quadruple, generated from `prod_json.json` cross-referenced with each comercio's categories and presentations.
- Add `backend/db/seeds/seeds/producto_presentaciones.py` that loads the JSON into one target database at a time.
- The presentation policy is encoded at JSON-generation time by category: pizzas → [GRANDE, CHICA], empanadas → [UNIDAD], bebidas → [LATA, LITRO, DOS_LITROS], postres → [KILO]. The script does not know this policy; it consumes the generated JSON.
- The JSON references each parent by business key (`comercio_cuit`, `categoria_descripcion`, `producto_nombre`, `presentacion_codigo`); the script resolves all four to ids at run time.
- The script performs a four-way integrity check before each insert: the `comercio_cuit` exists, the `categoria_descripcion` exists for that comercio, the `producto_nombre` exists in that categoria, and the `presentacion_codigo` exists for that comercio. This guarantees that the inserted join row only references rows that share the same `comercio_id`.
- The script is idempotent on the composite `(id_producto, id_presentacion)` pair (the model's `UniqueConstraint producto_presentacion_unico`).
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-producto-presentaciones`: An idempotent seed operation that populates `producto_presentaciones` from a JSON data file into the selected database, resolving each row's four parent references via business keys at insert time and verifying all four resolve to rows in the same comercio.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/producto_presentaciones.json`, `backend/db/seeds/seeds/producto_presentaciones.py`.
- **Read-only reference**: `backend/db/seeds/data/prod_json.json` (product catalog, not modified by this change).
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependencies**: requires `comercios`, `categorias_productos`, `productos`, and `presentaciones` rows to exist in the target DB. All four are seeded by earlier subphases.
