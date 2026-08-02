## Context

Mirrors the prior seed subphases. Code under `backend/db/seeds/` (script in `seeds/` subfolder per the same convention as `estados_comercio.py`, `metodos_entrega.py`, etc.). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

Unlike the previous join-table seeds (`comercio_medios_pago`, `comercio_metodos_entrega`), this seed targets a regular table with a single FK rather than a composite-pair join table. Two design points specific to this change:

- **Idempotency key.** The `CategoriaProducto` model has no `UniqueConstraint` on `(id_comercio, descripcion)`. The script uses the pair as a Python-level dedup key, mirroring the natural business key (each comercio's categories are uniquely named within that comercio). The DB itself will not enforce uniqueness; this is intentional per the existing model spec.
- **Parent referenced by business key, not id.** Same rationale as prior cross-reference seeds: the JSON must work across DBs with different autoincrement histories.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on the composite `(id_comercio, descripcion)` pair.** Natural business key, applied as a Python-level dedup (no DB constraint exists).
- **D3 — Parent referenced by business key, not id.** Decouples the JSON from autoincrement histories.
- **D4 — JSON data file, not embedded constants.** Source of truth lives next to the script.
- **D5 — Unknown `comercio_cuit` fails loudly.** A typo raises `ValueError` instead of silently inserting nothing.

## Risks / Trade-offs

- **[Risk] Stale JSON after a comercio rename.** → Mitigation: if a `comercio_cuit` is changed in a future seed, the rows referencing the old key are skipped automatically by the lookup. Operators who want to delete stale category rows must do so out of band.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
