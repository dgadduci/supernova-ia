## Why

`metodos_entrega` is empty on both `supernova` and `supernova_test`. `comercio_metodos_entrega.id_metodo_entrega` (Subphase 1.9) FKs to `metodos_entrega.id`, so child rows cannot be inserted without catalog rows. This change seeds the global delivery-method catalog so downstream seeds and smoke tests can attach comercios to métodos de entrega.

## What Changes

- Add `backend/db/seeds/data/metodos_entrega.json` with the seed rows.
- Add `backend/db/seeds/seeds/metodos_entrega.py` that loads the JSON into one target database at a time.
- The script is idempotent: rows whose `codigo` already exists are skipped.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-metodos-entrega`: An idempotent seed operation that populates `metodos_entrega` from a JSON data file into the selected database, selectable per-run via `SUPERNOVA_DATABASE_URL`.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/metodos_entrega.json`, `backend/db/seeds/seeds/metodos_entrega.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK consumers**: enables `comercio_metodos_entrega` seeds and smoke tests.
