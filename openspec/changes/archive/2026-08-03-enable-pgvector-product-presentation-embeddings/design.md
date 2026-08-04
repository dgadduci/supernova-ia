## Context

The application already persists `ProductoPresentacion` rows in PostgreSQL and uses migrations for schema evolution, but there is no database-native vector type or durable embedding record. Subphase 4.3 introduces pgvector-backed persistence while preserving the existing product-presentation ownership model and keeping embedding generation/search orchestration out of scope.

## Goals / Non-Goals

**Goals:**

- Enable the PostgreSQL `vector` extension through a repeatable migration.
- Persist one embedding per product presentation and embedding model, with a fixed configured dimension.
- Provide an idempotent persistence boundary for insert/update and retrieval.
- Enforce foreign-key cleanup, uniqueness, dimensionality, and metadata requirements at the database/model boundary.
- Make deployment and rollback behavior explicit and testable.

**Non-Goals:**

- Selecting an embedding provider or generating embeddings.
- Implementing semantic similarity queries, ranking, or product-recognition behavior.
- Backfilling embeddings for existing catalog records.
- Adding an approximate nearest-neighbor index before query workloads and distance strategy are defined.

## Decisions

1. **Use PostgreSQL pgvector with SQLAlchemy's vector type.**
   The migration will create the `vector` extension and the embedding column will use a fixed dimension from application configuration. This keeps dimensionality enforced by PostgreSQL and avoids serializing vectors as JSON or binary blobs. Alternatives considered: JSON/array storage, rejected because it removes database type validation and makes future distance operations less direct; a separate vector store, rejected because it adds operational complexity and breaks transactional ownership with the catalog.

2. **Model embeddings as a dedicated child table.**
   A dedicated `producto_presentacion_embeddings` table will reference `producto_presentaciones.id` with `ON DELETE CASCADE`, store the vector, provider/model identifier, and timestamps, and use a unique constraint on `(id_producto_presentacion, modelo)`. This supports model replacement without overwriting unrelated model versions while preserving idempotent writes. Alternatives considered: columns directly on `producto_presentaciones`, rejected because multiple models and lifecycle metadata do not fit cleanly; an unowned document store, rejected because consistency and cleanup become application responsibilities.

3. **Expose persistence through an idempotent repository/service operation.**
   The write path will upsert by presentation and model, replacing the vector and update timestamp when the same key already exists. Reads will return the persisted record by presentation/model. Generation, validation of provider semantics, and similarity search remain callers' responsibilities; persistence validates vector shape and required metadata.

4. **Defer vector indexes.**
   The initial migration creates the extension and table but no HNSW/IVFFlat index. Index choice depends on the eventual distance metric, data volume, and query patterns. A plain type-backed column is sufficient for persistence and avoids premature migration/runtime costs.

## Risks / Trade-offs

- **[Risk] Deployment targets do not permit `CREATE EXTENSION`.** → Validate extension availability in migration/integration checks and document the PostgreSQL image/managed-service prerequisite before rollout.
- **[Risk] Embedding provider dimension changes.** → Keep the dimension in configuration, reject mismatched vectors at the persistence boundary, and require a deliberate schema/configuration migration for dimension changes.
- **[Risk] Existing product-presentation deletes leave stale records if ORM/database cascade is incomplete.** → Use database `ON DELETE CASCADE`, configure the relationship consistently, and test deletion at the database-backed integration level.
- **[Risk] Upsert behavior can hide accidental model identity changes.** → Make the model/provider identifier part of the unique key and require callers to supply it explicitly.
- **[Trade-off] No similarity index initially.** → Persistence is simpler and safer, but similarity queries will require a later indexed migration once workload characteristics are known.

## Migration Plan

1. Deploy the migration that creates the pgvector extension and embedding table/constraints.
2. Deploy the model and repository code with embedding writes disabled or only invoked by the new caller path.
3. Verify extension availability, table constraints, idempotent upsert, and cascade deletion in staging.
4. Enable the Subphase 4.3 caller after validation; do not backfill existing rows in this change.
5. Roll back application code first if needed. Roll back the migration only after removing embedding rows and dependent code; dropping the extension is optional and must not be performed if other application features use it.

## Open Questions

- What embedding provider/model identifier and vector dimension will the first production caller use?
- Which similarity metric and index strategy should be selected for the follow-up retrieval capability?
- Should model identifiers be constrained to a registry table, or remain opaque metadata owned by the embedding caller?
