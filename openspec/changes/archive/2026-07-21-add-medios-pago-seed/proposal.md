## Why

`medios_pago` is empty on both `supernova` and `supernova_test`. `comercio_medios_pago.id_medio_pago` (Subphase 1.10) FKs to `medios_pago.id`, so child rows cannot be inserted without catalog rows. This change seeds the global payment-method catalog so downstream seeds and smoke tests can attach commerces to medios de pago.

## What Changes

- Add `backend/db/seeds/data/medios_pago.json` with the seed rows.
- Add `backend/db/seeds/medios_pago.py` that loads the JSON into one target database at a time.
- The script is idempotent: rows whose `codigo` already exists are skipped.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test`.
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-medios-pago`: An idempotent seed operation that populates `medios_pago` from a JSON data file into the selected database, selectable per-run via `SUPERNOVA_DATABASE_URL`.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New files**: `backend/db/seeds/data/medios_pago.json`, `backend/db/seeds/medios_pago.py`.
- **DBs touched**: `supernova_test` and `supernova`.
- **FK consumers**: enables `comercio_medios_pago` seeds and smoke tests.
