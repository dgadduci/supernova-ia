## Context

Mirrors the prior seed subphases. Code under `backend/db/seeds/` (script in `seeds/` subfolder per the same convention as `estados_comercio.py` and `metodos_entrega.py`). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

This is the second cross-reference seed. Same two design points as `seeds-comercio-medios-pago`, with one model-specific addition:

- **Business-key indirection.** `comercios` and `metodos_entrega` each have different autoincrement histories in `supernova` vs `supernova_test`. Embedding `id_comercio` / `id_metodo_entrega` would couple the JSON to one DB. The script does two small lookups and resolves both keys at insert time.
- **Idempotency on the composite pair.** The model already declares `UniqueConstraint comercio_metodo_unico` over `(id_comercio, id_metodo_entrega)`. The script queries existing pairs and skips any row whose composite is already present.
- **`orden` supplied explicitly per row.** `ComercioMetodoEntrega.orden` has no default (mirrors the catalog's `MetodosEntrega.orden`). The JSON includes an `orden` value per row.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on the composite `(id_comercio, id_metodo_entrega)` pair.** Matches the model's unique constraint.
- **D3 — Parents referenced by business key, not id.** Decouples the JSON from autoincrement histories.
- **D4 — JSON data file, not embedded constants.** Source of truth lives next to the script.
- **D5 — `orden` supplied explicitly per row in the JSON.** Required by the model; no default exists.
- **D6 — Unknown parent key fails loudly.** A typo in `comercio_cuit` or `metodo_entrega_codigo` raises `ValueError` instead of silently inserting nothing.

## Risks / Trade-offs

- **[Risk] Stale JSON after a parent rename.** → Mitigation: if a `comercio_cuit` or `metodo_entrega_codigo` is changed in a future seed, the rows referencing the old key are skipped automatically by the lookup. Operators who want to delete stale join rows must do so out of band.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
