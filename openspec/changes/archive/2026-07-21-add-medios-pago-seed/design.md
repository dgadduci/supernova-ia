## Context

Mirrors `seeds-estado-comercio` and `seeds-comercios`. Code under `backend/db/seeds/` and `backend/db/seeds/data/`. DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

The `MediosPago` model has `codigo` declared `unique=True` — unlike `Comercio.cuit` which is only indexed. Idempotency on `codigo` is therefore both natural (the model already enforces uniqueness) and safe (no false positives from non-unique business keys).

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on `codigo`.** Matches the model's natural unique key.
- **D3 — JSON data file, not embedded constants.** Source of truth lives next to the script.

## Risks / Trade-offs

- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
