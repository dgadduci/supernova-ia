## Why

`comercios` is empty on both `supernova` and `supernova_test`. The `comercio_metodos_entrega`, `comercio_medios_pago`, `categoria_producto`, and `presentacion` join tables all FK to `comercios.id`, and the `estado_id` column FKs to `estado_comercio.id` (already seeded). Without seed rows, no downstream smoke test or demo can create child rows. This change adds the seed for `comercios` so the table has a usable starting state in both DBs.

## What Changes

- Add `backend/db/seeds/data/comercio.json` containing the seed rows.
- Add `backend/db/seeds/comercios.py` that loads the JSON into one target database at a time.
- The script is idempotent: rows whose `cuit` already exists are skipped.
- The JSON references each row's estado by **code** (`estado_codigo`), not id; the script resolves the code against `estado_comercio` at run time. This keeps the JSON portable across DBs where the same estado has different ids.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-comercios`: An idempotent seed operation that populates `comercios` from a JSON data file into the selected database, selectable per-run via `SUPERNOVA_DATABASE_URL`. Estado is referenced by code in the JSON and resolved against the live `estado_comercio` table at insert time.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/comercio.json`, `backend/db/seeds/comercios.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK dependency**: requires `estado_comercio` rows to exist in the target DB (already true after the previous seed subphase).
