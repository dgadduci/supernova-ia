## 1. Repository and configuration

- [x] 1.1 Inspect the existing migration, SQLAlchemy model, repository, dependency, and test conventions for product presentations.
- [x] 1.2 Add the pgvector SQLAlchemy integration dependency and configured embedding dimension/model settings using the project's existing configuration pattern.

## 2. Database schema

- [x] 2.1 Create a migration that enables the PostgreSQL `vector` extension before creating embedding tables.
- [x] 2.2 Create the product-presentation embedding table with vector dimension, model metadata, timestamps, foreign key cascade, indexes, and uniqueness constraints.
- [x] 2.3 Add a reversible migration downgrade that removes the embedding table and only removes the extension when safe for the schema's ownership contract.

## 3. Domain model and persistence

- [x] 3.1 Implement the embedding SQLAlchemy model and add the `ProductoPresentacion.embeddings` relationship with cascade behavior.
- [x] 3.2 Implement idempotent create-or-update persistence keyed by product presentation and model identifier.
- [x] 3.3 Implement retrieval by product presentation and model identifier, including validation for required identifiers and configured vector dimensionality.
- [x] 3.4 Ensure foreign-key failures and invalid vectors produce the project's standard persistence errors without orphan rows.

## 4. Verification

- [x] 4.1 Add model metadata tests for the vector column, foreign key cascade, timestamps, relationship, and uniqueness constraint.
- [x] 4.2 Add PostgreSQL migration/integration tests proving extension creation, table constraints, upsert behavior, dimension rejection, and cascade deletion.
- [x] 4.3 Run the project's lint, typecheck, and relevant test commands and resolve failures.
