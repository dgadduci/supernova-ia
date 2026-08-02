## Context

The current context resolver combines catalog loading, SQLAlchemy query construction, recognizer invocation, and intent transformation. Project rules require internal components to use the Service → Repository → SQLAlchemy layering, while the context resolver should remain a pure decision function. The refactor crosses the resolver, product data access, orchestration, and tests but does not change persistence or database schema.

## Goals / Non-Goals

**Goals:**
- Put candidate-restricted database access in the existing product repository/service layers.
- Keep catalog construction consistent with the recognizer's exact 12-field contract.
- Make `ProductSelectionContextResolver` independent of SQLAlchemy and sessions.
- Provide a thin service boundary that loads data and invokes the pure resolver.

**Non-Goals:**
- Changing recognizer fuzzy logic or output fields.
- Adding handlers, response generation, pending-context persistence, or migrations.
- Expanding the resolver beyond selection transformation.

## Decisions

- Inspect and extend the existing product repository/service rather than introducing a parallel data-access stack. This preserves established layering and transaction conventions.
- Expose a repository/service operation that accepts candidate IDs and eager-loads the product, presentation, and category relationships. Filtering remains at the repository query boundary.
- Keep the 12-field catalog construction in the service, adjacent to the loaded ORM data, so the resolver receives plain dictionaries and has no model dependency.
- Change the resolver signature to `(message, active_intent, productos_presentaciones)` and retain its existing unchanged-result and successful-result semantics.
- Add an orchestration service that owns the session input, calls the product service, and delegates to the pure resolver. It will not commit or mutate session state.
- Test repository filtering and service shaping independently, then test the orchestration path with the real recognizer.

## Risks / Trade-offs

- [Risk] Existing callers use the old resolver signature → Mitigation: update only known call sites and tests in this scoped subphase; the signature change is intentional.
- [Risk] Catalog fields drift between service and recognizer → Mitigation: assert the exact 12-key set and run a real-recognizer integration test.
- [Risk] Repository method duplicates an existing query → Mitigation: inspect current product services/repositories first and reuse an equivalent method when available.

## Migration Plan

1. Inventory current product repository/service APIs and resolver call sites.
2. Add or reuse candidate catalog loading through repository and service layers.
3. Move catalog construction into the service and simplify the resolver signature.
4. Add orchestration and focused tests.
5. Run smoke tests and compilation; rollback by restoring the previous resolver/query path if callers are not yet migrated.

## Open Questions

The exact existing product service/repository class and module for the orchestration wrapper will be selected after inspecting neighboring implementations; no new architectural layer is intended.
