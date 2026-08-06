## ADDED Requirements

### Requirement: Local-admin endpoints consume the existing seeder and indexer surface

The local administrative FastAPI endpoints added in Subphase 4.7 SHALL delegate to `ProductoPresentacionEmbeddingSeeder.run(...)` and shall not duplicate the indexer's batching, hash comparison, stale / inactive / failed handling, dry-run classification, or embedding-client orchestration. The Subphase 4.6 indexer / seeder / service / repository public surface SHALL remain unchanged. The `OllamaEmbeddingClient` constructor SHALL remain `(settings, transport=None, clock=None)`. The `--batch-size` override SHALL flow through `dataclasses.replace(settings, embedding_batch_size=batch_size)` on the frozen `Settings` when supplied through the HTTP path (the persisted `Settings` is unchanged). All other Subphase 4.6 behavior — including the 4.6 CLI, the indexer's no-commit / no-rollback / no-close / no-begin contract, and the strict `--dry-run` semantics — SHALL be preserved.

#### Scenario: HTTP reindex produces the same counters as the 4.6 CLI

- **WHEN** the HTTP reindex endpoint is called with the same commerce scope as a 4.6 CLI invocation against the same catalog
- **THEN** the aggregated `created`, `updated`, `unchanged`, `stale`, `inactive`, and `failed` counters match the CLI summary line
- **AND** the embedding client is called the same number of times as the equivalent CLI run

#### Scenario: HTTP reindex dry-run is strictly read-only

- **WHEN** the HTTP reindex endpoint is called with `dry_run=True`
- **THEN** `service.mark_stale(row)` is NOT called
- **AND** `service.mark_inactive(row)` is NOT called
- **AND** `embedding_client.embed_documents(...)` is NOT called
- **AND** `repository.insert_document` / `update_document` / `mark_status` are NOT called
- **AND** `session.flush()` is NOT called
- **AND** `session.commit()` is NOT called
- **AND** the endpoint reports `failed=0` because Ollama-side failures cannot be predicted during `--dry-run`

#### Scenario: HTTP reindex preserves the per-batch failure semantics

- **WHEN** the embedding client raises `EmbeddingClientError` for a batch during an HTTP reindex
- **THEN** every document in the failing batch transitions to `embedding_status='failed'` through `service.record_failed_document(...)`
- **AND** the endpoint commits the failed rows once and returns `200` with the populated `failed` count instead of re-raising the `EmbeddingClientError`

#### Scenario: 4.6 CLI and migration remain unchanged

- **WHEN** Subphase 4.6's CLI runner (`backend/scripts/seed_product_presentation_embeddings.py`) and its tests are exercised after Subphase 4.7 lands
- **THEN** they continue to pass without modification
- **AND** the 4.6 migration remains the only migration for `producto_presentacion_embeddings`
- **AND** the `OllamaEmbeddingClient` constructor is unchanged
