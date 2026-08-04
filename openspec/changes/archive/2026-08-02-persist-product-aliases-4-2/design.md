## Context

The active fuzzy implementation owns two different alias concepts. `ALIASES_PALABRAS` contains fourteen spelling/abbreviation substitutions used during product-name normalization, while `PRESENTACION_ALIASES` supports structured presentation extraction and pending-candidate narrowing. Subphase 4.2 moves only real product aliases from `ALIASES_PALABRAS`; presentation values and resolver-specific narrowing aliases remain unchanged.

Recognition is pure and receives a caller-built product-presentation catalog. Commerce-wide catalogs are projected by `ProductoQueryService`, while pending and modification flows use restricted product-presentation IDs. Subphase 4.1 froze the protocol, dictionary result shape, ranking, ordering, quantity behavior, and representative baseline cases. Database queries therefore belong outside the recognizer and aliases must be attached to each catalog row before `ProductRecognizerProtocol` is invoked.

The current active substitutions are `muza`, `muzza`, `muzarela`, `muzarella`, `mozarela`, `mozarella`, `muzzarela`, `muzzarella`, `musarela`, `musarella`, `fugazeta`, `fugazetta`, `napoli`, and `calabreza`. The fugazzeta, napolitana, and calabresa ownership is safely derivable from exact canonical product names. The mozzarella substitutions require an explicit ownership decision because more than one product name may contain the canonical term in one commerce; implementation must stop rather than select by a partial match.

## Goals / Non-Goals

**Goals:**

- Persist active product-wide and product-presentation aliases with normalized lookup data and database-enforced scope uniqueness.
- Preserve the current alias normalization and fuzzy recognition behavior while making PostgreSQL the sole production alias authority.
- Keep alias queries commerce-scoped and restricted-candidate recognition restricted.
- Provide repository/service boundaries and an idempotent, safely resolving seeder.
- Prove migration, seeding, scope isolation, and Subphase 4.1 compatibility with automated tests.

**Non-Goals:**

- Persisting ordinary presentation values or changing `PRESENTACION_ALIASES`, `_extraer_presentacion`, pending narrowing, or resolver behavior.
- Adding alias administration APIs or UI.
- Adding pgvector, embeddings, Ollama, semantic scoring, or a hybrid recognizer.
- Changing fuzzy thresholds, score calculation, ordering, grouping, quantity handling, customer responses, or pending queues.
- Synchronizing or archiving the change automatically.

## Decisions

1. **Use one nullable-scope table.** Add `producto_aliases` with the project-standard integer primary key, `id_producto`, nullable `id_producto_presentacion`, `alias`, `alias_normalizado`, `activo`, `fecha_alta`, and `fecha_ultima_modificacion`. A null presentation means product-wide applicability; a non-null presentation means exact product-presentation applicability. Separate tables were rejected because they duplicate validation, querying, and seeding behavior.

2. **Enforce same-scope uniqueness with PostgreSQL partial unique indexes.** One unique index covers `(id_producto, alias_normalizado)` where `id_producto_presentacion IS NULL`; another covers `(id_producto, id_producto_presentacion, alias_normalizado)` where it is non-null. Ordinary indexes cover both foreign keys, normalized alias, and activity. A conventional nullable composite unique constraint was rejected because PostgreSQL treats nulls as distinct and would permit duplicate product-wide aliases.

3. **Validate cross-row ownership in the service.** The service normalizes through the recognizer's existing text-normalization contract, rejects empty normalized values, verifies that a presentation-specific row belongs to `id_producto`, and checks duplicates before persistence. The database foreign keys and unique indexes remain the race-safe final guard. A database check constraint cannot verify ownership across `producto_presentaciones`, so service validation is required.

4. **Keep transaction ownership outside the alias service.** Repositories contain all SQLAlchemy queries. Services neither commit, roll back, close, nor begin sessions. The standalone seeder owns one outer transaction so an unsafe mapping or validation failure cannot silently commit a partial transfer.

5. **Attach recognition-ready aliases at the catalog projection boundary.** Catalog rows receive an optional `aliases` collection containing all active product-wide aliases for their `id_producto` plus only active aliases for their exact `producto_presentacion_id`. Commerce-wide projection is constrained through the existing commerce catalog query; restricted flows query only their candidate product-presentation IDs. The recognizer remains infrastructure-free and never expands the supplied catalog.

6. **Preserve matching semantics through characterization before replacement.** Before changing alias application, tests record every active hardcoded substitution's normalized input, eligible candidates, scores/ranking where observable, and ambiguity. Runtime alias handling is then driven only by caller-provided alias data but must produce the same results for migrated product aliases. A generic fallback to the hardcoded map is allowed only during implementation and must be removed before completion.

7. **Do not migrate presentation vocabulary.** `PRESENTACION_ALIASES`, including size/unit forms and the existing `picante`/`tradicional` pending-narrowing behavior, remains structured recognizer data. Values such as `chica`, `grande`, `unidad`, and `1 litro` are not inserted into `producto_aliases` merely because they occur in the presentation catalog.

8. **Resolve seed targets by exact stable catalog data, never IDs or partial names.** Seeder definitions identify canonical products and, when needed, presentations through exact stable names/codes. Each mapping must resolve exactly once per intended commerce scope. Zero or multiple matches are reported as failed and abort the transaction. Repeated execution compares normalized alias and scope, inserts nothing twice, preserves unrelated rows, and reports inserted, unchanged, skipped, and failed counts.

9. **Use PostgreSQL as the only final authority.** The migration creates storage without changing recognition by itself. The seeder runs before hardcoded substitutions are removed. Production integration switches only after repository/service and compatibility tests pass; completion requires no second production alias source.

## Risks / Trade-offs

- **[Risk] A normalized alias can be valid for multiple products and create ambiguity.** → Keep aliases non-global, return every applicable catalog row, and preserve candidate grouping rather than forcing uniqueness.
- **[Risk] The mozzarella substitutions have unsafe ownership if resolved by substring.** → Require an explicit exact-name mapping decision before implementation; fail the seeder on zero or multiple matches.
- **[Risk] Moving from global token substitution to row-scoped aliases can alter scores or ordering.** → Characterize all current aliases first and block hardcoded-source removal until contract and baseline comparisons pass.
- **[Risk] Presentation-specific aliases could leak to sibling presentations or another commerce.** → Scope repository queries by commerce and requested IDs, and test exact-row projection.
- **[Risk] Application validation can race.** → Retain database partial unique indexes and translate integrity failures through the existing service error conventions.
- **[Risk] Seeder failure after inserts could leave partial state.** → Run all resolution and writes in one outer transaction and roll back on any failed required mapping.
- **[Trade-off] Alias loading adds a query or eager-loading cost to catalog construction.** → Batch by requested product and product-presentation IDs; never query per catalog row.

## Migration Plan

1. Inventory and classify all active aliases; resolve the mozzarella ownership question before data changes.
2. Add the model, relationships, and reversible Alembic migration; upgrade the test database and verify constraints/indexes.
3. Add repository/service behavior and model/service tests.
4. Add and dry-run the idempotent seeder; require exact target resolution, then run it twice and verify the second run inserts zero rows.
5. Add batched alias enrichment to commerce and restricted catalog projections.
6. Switch the pure recognizer to caller-provided aliases behind compatibility tests, then remove `ALIASES_PALABRAS` as a production source.
7. Run the Subphase 4.1 contract/baseline suite and focused add, pending selection, remove, and modify regressions.
8. Deploy by applying the migration, running the seeder successfully, and then deploying application code that requires persisted aliases.

Rollback reverses application code first so the deployed recognizer does not depend on a table that will be removed, then downgrades the additive migration. If compatibility fails before deployment, retain the existing runtime source and roll back the catalog-enrichment changes; do not leave a partially migrated authoritative state.

## Open Questions

- Which exact canonical product or products own the ten mozzarella spelling aliases in each commerce where both `Pizza de Muzzarella` and another mozzarella-named product exist?
- Does deployment execute the alias seeder as a separate controlled release step or through the existing seed orchestration after `producto_presentaciones`?
