## Context

Mirrors the `seeds-estado-comercio` change (the prior seed subphase). Code lives under purpose-specific subdirectories (`backend/db/seeds/` for scripts, `backend/db/seeds/data/` for JSON payloads). DB selection reuses `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

The two design points specific to this change:

- **Idempotency key: `cuit`.** The model indexes `cuit` but does not declare it unique. `cuit` is the most stable business identifier for a comercio, so the script uses it as the dedup key. Re-runs against an already-seeded table skip all rows whose CUIT is already present.
- **`estado_codigo` instead of `estado_id`.** Estado ids differ between `supernova` and `supernova_test` (different autoincrement histories). Embedding `estado_id` would couple the JSON to one specific DB. The script joins against `estado_comercio` at run time so the same JSON seeds either DB correctly.

## Decisions

- **D1 — One script, one DB at a time.** Same as the prior seed; no cross-DB writes.
- **D2 — Idempotent on `cuit`.** Stable business key, not a transient autoincrement.
- **D3 — Estado by code.** JSON holds `estado_codigo`; script resolves to `estado_id` at run time.
- **D4 — JSON data file, not embedded constants.** Source of truth lives next to the script; future edits to the JSON take effect on the next run.

## Risks / Trade-offs

- **[Risk] Missing `estado_codigo` in the JSON.** → Mitigation: the script raises `ValueError` rather than silently defaulting, so a typo fails loudly.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
