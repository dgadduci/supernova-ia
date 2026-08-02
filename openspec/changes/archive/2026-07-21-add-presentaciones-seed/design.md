## Context

Mirrors the prior seed subphases. Code under `backend/db/seeds/` (script in `seeds/` subfolder per the same convention as the other seed scripts). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

This seed follows the same per-comercio ownership pattern as `categorias_productos`. Two model-specific notes:

- **Two unique constraints exist.** `Presentacion` declares both `comercio_presentacion_codigo_unico` (on `(id_comercio, codigo)`) and `comercio_presentacion_descripcion_unica` (on `(id_comercio, descripcion)`). The script's idempotency uses the `codigo` pair, which is the more stable business key.
- **`descripcion` is unique per comercio.** The JSON must avoid collisions between presentations for the same comercio on either key. The starter set uses distinct Spanish names per row.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on the composite `(id_comercio, codigo)` pair.** Mirrors the model's primary unique key (the more stable of the two).
- **D3 — Parent referenced by business key, not id.** Decouples the JSON from autoincrement histories.
- **D4 — JSON data file, not embedded constants.** Source of truth lives next to the script.
- **D5 — Unknown `comercio_cuit` fails loudly.** A typo raises `ValueError` instead of silently inserting nothing.

## Risks / Trade-offs

- **[Risk] Stale JSON after a comercio rename.** → Mitigation: if a `comercio_cuit` is changed in a future seed, the rows referencing the old key are skipped automatically by the lookup. Operators who want to delete stale presentation rows must do so out of band.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
