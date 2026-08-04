## ADDED Requirements

### Requirement: Product-presentation embedding persistence
The system SHALL define a persistence model and database table for embeddings associated with a `ProductoPresentacion`. Each embedding SHALL include a primary key, a non-null `id_producto_presentacion` foreign key to `producto_presentaciones.id` with `ON DELETE CASCADE`, a non-null vector with the configured embedding dimension, a non-null embedding model identifier, and lifecycle timestamps. The table SHALL enforce uniqueness for `(id_producto_presentacion, modelo)`.

#### Scenario: Embedding exposes required persisted fields
- **WHEN** the embedding model and table metadata are inspected
- **THEN** the table exposes the product-presentation foreign key, vector column with the configured dimension, model identifier, and lifecycle timestamps
- **AND** the product-presentation foreign key is indexed and configured with `ON DELETE CASCADE`

#### Scenario: Embeddings are unique per presentation and model
- **WHEN** a second embedding is persisted for the same product presentation and model identifier
- **THEN** persistence rejects a duplicate row or updates the existing row through the defined upsert operation
- **AND** two different model identifiers may coexist for the same product presentation

### Requirement: Idempotent embedding persistence operations
The system SHALL provide an application persistence boundary that stores or updates an embedding by product presentation and model identifier and retrieves it by that same identity. The operation SHALL validate required identifiers and vector dimensionality before persistence and SHALL preserve the latest vector and modification timestamp on update.

#### Scenario: New embedding is persisted
- **WHEN** a valid product-presentation identifier, model identifier, and vector with the configured dimension are submitted
- **THEN** one embedding row is created and can be retrieved by product presentation and model identifier

#### Scenario: Existing embedding is updated idempotently
- **WHEN** a valid vector is submitted for an identity that already has an embedding
- **THEN** no duplicate row is created
- **AND** the stored vector is replaced and the modification timestamp is updated

#### Scenario: Invalid vector dimension is rejected
- **WHEN** a vector whose length differs from the configured embedding dimension is submitted
- **THEN** the persistence operation rejects it before creating or modifying a row

#### Scenario: Missing product presentation is rejected
- **WHEN** an embedding references a product-presentation identifier that does not exist
- **THEN** persistence rejects the operation without creating an orphan embedding row

### Requirement: pgvector extension availability
The database schema SHALL enable PostgreSQL's `vector` extension before creating the embedding vector column. Applying the migration to a supported PostgreSQL database SHALL make the extension available for the embedding table.

#### Scenario: Migration enables vector support
- **WHEN** the embedding migration is applied to a supported PostgreSQL database
- **THEN** the `vector` extension exists before the embedding table is created
- **AND** the embedding vector column is created with the configured dimension

#### Scenario: Product-presentation deletion cascades to embeddings
- **WHEN** a product presentation with persisted embeddings is deleted
- **THEN** all embeddings owned by that product presentation are deleted by the database cascade
- **AND** no orphan embedding rows remain
