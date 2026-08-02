## Why

Phase 1 finished with an empty `estado_comercio` table on both `supernova` and `supernova_test`. The `Comercio.estado_id` FK introduced in Subphase 1.2 cannot be satisfied without catalog rows, so any future seed / fixture / smoke test that creates a `Comercio` needs the estado catalog to be populated first. This change adds the first seed operation: a single script that loads the estado catalog into both DBs.

## What Changes

- Add `backend/db/seeds/seeds/estados_comercio.py` that loads `estado_comercio` rows from `backend/db/seeds/data/estados.json` into one target database at a time.
- The script is idempotent: rows whose `estado` value already exists are skipped.
- Target database is selected via `SUPERNOVA_DATABASE_URL`; defaults to `supernova_test` (matches the Alembic convention from Subphase 1.11).
- Both DBs are seeded as part of this change.

## Capabilities

### New Capabilities

- `seeds-estado-comercio`: An idempotent seed operation that populates `estado_comercio` from a JSON data file into the selected database, selectable per-run via `SUPERNOVA_DATABASE_URL`.

### Modified Capabilities

_None._ No model or existing spec changes.

## Impact

- **New file**: `backend/db/seeds/seeds/estados_comercio.py`.
- **Data source**: `backend/db/seeds/data/estados.json` (already present).
- **DBs touched**: `supernova_test` and `supernova`.
