## Context

Mirrors the prior seed subphases. Code under `backend/db/seeds/` (script in `seeds/` subfolder per the same convention as the other seed scripts). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

This seed differs from the prior ones in three ways:

- **Four-way parent resolution.** Every row references four parents (comercio, categoria, product, presentation) instead of the usual one or two. The script does four small lookups per row.
- **Cross-table integrity invariant.** The user explicitly requires that the categoria, the product, and the presentation all belong to the same comercio. The script enforces this by resolving each reference *through* that comercio (the categoria lookup is keyed by `(id_comercio, descripcion)`; the product lookup is keyed by the resolved categoria id; the presentation lookup is keyed by `(id_comercio, codigo)`). A mismatch raises `ValueError` before any insert happens, so a stale or wrong JSON cannot leak into the join table.
- **Per-category presentation policy at generation time.** The rule "pizzas get two presentations, empanadas get one, etc." lives in the generator, not in the script. The script is policy-free; changing the policy means regenerating the JSON, not editing the script.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on the composite `(id_producto, id_presentacion)` pair.** Mirrors the model's unique constraint.
- **D3 — All four parent references resolved at insert time.** `comercio_cuit`, `categoria_descripcion` (case-insensitive, lower-folded), `producto_nombre`, `presentacion_codigo`. Decouples the JSON from autoincrement histories.
- **D4 — Cross-table integrity verified per row.** A row whose any reference fails to resolve to a row in the same comercio raises `ValueError`; the script inserts nothing for that row and the transaction is rolled back if any row fails (single transaction).
- **D5 — JSON data file, not embedded constants.** Source of truth lives next to the script. The catalog itself (`prod_json.json`) is a separate, human-editable file consumed at generation time.
- **D6 — Presentation policy lives in the generator, not the script.** Adding a new (categoria → presentations) rule is a JSON-regeneration step, not a script edit.

## Risks / Trade-offs

- **[Risk] Stale JSON after a catalog or presentation edit.** → Mitigation: the script consumes `producto_presentaciones.json`, not `prod_json.json`, so the operator regenerates explicitly. Intentional: the seed input remains a reviewable file.
- **[Risk] A typo in any of the four references silently fails the integrity check.** → Mitigation: the script raises `ValueError` with a specific message naming the offending `(comercio, categoria, producto, presentacion)` tuple, so the JSON can be corrected.
- **[Risk] `presentacion_codigo` listed in the JSON does not exist for that comercio (e.g., KILO was not seeded).** → Mitigation: the script raises `ValueError`; the operator either seeds the missing presentation first or removes the row from the JSON.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
