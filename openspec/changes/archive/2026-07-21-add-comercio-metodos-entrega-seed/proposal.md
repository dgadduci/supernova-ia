## Why

`comercio_metodos_entrega` is empty on both `supernova` and `supernova_test`. The two parent catalogs (`comercios` and `metodos_entrega`) are now seeded by earlier subphases, but the join table itself has no rows, so any smoke test or demo that wants to display "this comercio offers these delivery methods" has nothing to show. This change seeds the full cartesian product of the two catalogs into the join table.

## What Changes

- Add `backend/db/seeds/data/comercio_metodos_entrega.json` with one row per (comercio, método de entrega) pair.
- Add `backend/db/seeds/seeds/comercio_metodos_entrega.py` that loads the JSON into one target database at a time.
- The JSON references each parent by business key (`comercio_cuit`, `metodo_entrega_codigo`); the script resolves both to ids against the live parent tables at run time. This keeps the JSON portable across DBs where the same parent has different ids.
- The script is idempotent on the composite `(id_comercio, id_metodo_entrega)` pair (the model's `UniqueConstraint comercio_metodo_unico`).
- Each row in the JSON supplies an explicit `orden` value because the `ComercioMetodoEntrega.orden` column has no Python-side or server-side default.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-comercio-metodos-entrega`: An idempotent seed operation that populates `comercio_metodos_entrega` from a JSON data file into the selected database, resolving each row's parent references via business keys (`comercio_cuit`, `metodo_entrega_codigo`) at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/comercio_metodos_entrega.json`, `backend/db/seeds/seeds/comercio_metodos_entrega.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependencies**: requires `comercios` (Subphase `seeds-comercios`) and `metodos_entrega` (Subphase `seeds-metodos-entrega`) rows to exist in the target DB.
