## Why

`comercio_medios_pago` is empty on both `supernova` and `supernova_test`. The two parent catalogs (`comercios` and `medios_pago`) are now seeded by earlier subphases, but the join table itself has no rows, so any smoke test or demo that wants to display "this comercio accepts these medios de pago" has nothing to show. This change seeds the full cartesian product of the two catalogs into the join table.

## What Changes

- Add `backend/db/seeds/data/comercio_medios_pago.json` with one row per (comercio, medio de pago) pair.
- Add `backend/db/seeds/seeds/comercio_medios_pago.py` that loads the JSON into one target database at a time.
- The JSON references each parent by business key (`comercio_cuit`, `medio_pago_codigo`); the script resolves both to ids against the live parent tables at run time. This keeps the JSON portable across DBs where the same parent has different ids.
- The script is idempotent on the composite `(id_comercio, id_medio_pago)` pair (the model's `UniqueConstraint comercio_medio_pago_unico`).
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-comercio-medios-pago`: An idempotent seed operation that populates `comercio_medios_pago` from a JSON data file into the selected database, resolving each row's parent references via business keys (`comercio_cuit`, `medio_pago_codigo`) at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/comercio_medios_pago.json`, `backend/db/seeds/seeds/comercio_medios_pago.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependencies**: requires `comercios` (Subphase `seeds-comercios`) and `medios_pago` (Subphase `seeds-medios-pago`) rows to exist in the target DB.
