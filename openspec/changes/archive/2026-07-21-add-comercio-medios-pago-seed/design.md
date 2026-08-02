## Context

Mirrors the prior seed subphases. Code under `backend/db/seeds/` (script in `seeds/` subfolder per the same convention as `estados_comercio.py` and `metodos_entrega.py`). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

This is the first cross-reference seed: it does not carry ids in the JSON, only business keys. Two design points specific to this change:

- **Business-key indirection.** `comercios` and `medios_pago` each have different autoincrement histories in `supernova` vs `supernova_test`. Embedding `id_comercio` / `id_medio_pago` would couple the JSON to one DB. The script does two small lookups and resolves both keys at insert time.
- **Idempotency on the composite pair.** The model already declares `UniqueConstraint comercio_medio_pago_unico` over `(id_comercio, id_medio_pago)`. The script queries existing pairs and skips any row whose composite is already present — the same shape the DB itself enforces.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on the composite `(id_comercio, id_medio_pago)` pair.** Matches the model's unique constraint.
- **D3 — Parents referenced by business key, not id.** Decouples the JSON from autoincrement histories.
- **D4 — JSON data file, not embedded constants.** Source of truth lives next to the script.
- **D5 — Unknown parent key fails loudly.** A typo in `comercio_cuit` or `medio_pago_codigo` raises `ValueError` instead of silently inserting nothing.

## Risks / Trade-offs

- **[Risk] Stale JSON after a parent rename.** → Mitigation: if a `comercio_cuit` or `medio_pago_codigo` is changed in a future seed, the rows referencing the old key are skipped automatically by the lookup. Operators who want to delete stale join rows must do so out of band.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
