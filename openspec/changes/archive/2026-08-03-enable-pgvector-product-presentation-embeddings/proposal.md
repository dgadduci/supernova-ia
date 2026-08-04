## Why

Product presentation records need semantic embeddings so future product-recognition and presentation-selection flows can retrieve the most relevant presentation from persisted catalog data. Subphase 4.3 must establish the PostgreSQL vector capability and durable embedding storage now, before similarity search consumers depend on it.

## What Changes

- Enable the PostgreSQL `vector` extension through the database migration layer.
- Add persistent embedding data for product presentations, including the vector value, embedding model metadata, and lifecycle timestamps.
- Associate each embedding with exactly one `ProductoPresentacion` and prevent duplicate embeddings for the same presentation and model.
- Add repository/service behavior to create or update embeddings idempotently and retrieve persisted embeddings for downstream similarity operations.
- Validate vector dimensionality and maintain referential cleanup when a product presentation is deleted.
- Add migration, model, persistence, and automated test coverage for extension availability and embedding lifecycle behavior.

## Capabilities

### New Capabilities
- `producto-presentacion-embeddings`: Persist and manage vector embeddings associated with product presentations.

### Modified Capabilities
- `producto-presentacion`: Extend product-presentation persistence requirements with embedding ownership and deletion behavior.

## Impact

The change affects PostgreSQL migrations and deployment prerequisites, SQLAlchemy models and relationships around `ProductoPresentacion`, persistence/service modules, and their tests. It introduces the PostgreSQL `pgvector` dependency and a vector column whose configured dimension must match the embedding provider contract; existing product-presentation deletion behavior must cascade to associated embedding records.
