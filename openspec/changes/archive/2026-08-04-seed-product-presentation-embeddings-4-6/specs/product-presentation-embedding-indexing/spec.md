## ADDED Requirements

### Requirement: Catalog projection includes active and inactive presentations

The system SHALL provide a per-document catalog projection that returns every applicable `producto_presentacion` regardless of `ProductoPresentacion.activo` so the indexer can reconcile the whole catalog. The projection SHALL accept optional `id_comercio`, `id_producto`, and `id_producto_presentacion` filters that compose by narrowing the scope. When all three filters are absent, the projection returns every presentation in the database (active and inactive); when any filter is present, only the matching presentations are returned (active and inactive). The projection SHALL load the parent catalog data (`Producto`, `CategoriaProducto`, `Presentacion`) and the applicable alias rows (`product`-scope and `product_presentacion`-scope, active only) needed by the pure `ProductEmbeddingDocumentBuilder`, and SHALL NOT filter on `activo` for the parent presentations. The projection SHALL also expose the parent `activo` flags so the indexer can detect inactive catalog chains before any embedding work.

#### Scenario: Projection includes inactive presentations

- **WHEN** the projection is called without filters against a catalog where presentation 31 belongs to an active product and presentation 42 belongs to an inactive `Producto`
- **THEN** both presentations appear in the projection result
- **AND** the parent chain (`Producto.activo`, `CategoriaProducto.activo`, `Presentacion.activo`, `ProductoPresentacion.activo`) is loaded so the indexer can decide which documents to mark `inactive`

#### Scenario: Filters compose and preserve inactive rows

- **WHEN** the projection is called with `id_comercio=1, id_producto=7`
- **THEN** only the presentations of product 7 in comercio 1 are returned
- **AND** inactive presentations of product 7 in comercio 1 are NOT silently dropped

#### Scenario: Aliases respect scope semantics

- **WHEN** the projection returns presentation 31 of product 7
- **THEN** the alias list contains every active `product`-scoped alias for product 7 plus every active `product_presentacion`-scoped alias whose `id_producto_presentacion=31`
- **AND** presentation-specific aliases whose `id_producto_presentacion` differs from 31 are excluded

### Requirement: Per-document indexer with hash-based idempotency

The system SHALL provide a `ProductoPresentacionEmbeddingIndexer` that, for each presentation in the projection, performs the inactive-catalog detection first and only then runs the pure `ProductEmbeddingDocumentBuilder` and the batched `embed_documents` flow. The hash-based idempotency decision lives in the indexer and the service (NOT in the repository); the repository performs only SQLAlchemy reads and writes (`insert_document`, `update_document`, `find_by_document`, `list_*`, `mark_status`). The indexer SHALL:

1. Inspect the parent chain (`Producto.activo`, `CategoriaProducto.activo`, `Presentacion.activo`, `ProductoPresentacion.activo`) for the presentation.
2. If any parent is inactive:
   - load the existing rows through `service.list_by_producto_presentacion_and_model(...)`;
   - transition every row to `inactive` through `service.mark_inactive(row)`;
   - do NOT run the pure `ProductEmbeddingDocumentBuilder`;
   - do NOT call `embed_documents`;
   - do NOT insert new active rows for that presentation.
3. If the chain is active, run the pure `ProductEmbeddingDocumentBuilder` to obtain the deterministic documents.
4. For each document, classify against the existing row through the service's `create_or_update_document(document, vector, *, modelo=settings.embedding_model, force=force)` (which owns the hash comparison AND the `embedding_status` / `activo` / `vector` / `force` checks):
   - `unchanged` is returned only when ALL of the following are true: stored `content_hash` equals the incoming `content_hash`; `embedding_status == 'ready'`; `activo == True`; the stored `vector` is present and has the configured dimension; `force == False`. When all five conditions hold, no Ollama call, no vector update, no `last_error` change, no `fecha_ultima_modificacion` advance, and no `flush()` for that row.
   - `updated` is returned when a row exists but ANY unchanged condition is false (hashes differ, OR status is `failed` / `stale` / `inactive`, OR `activo` is `False`, OR the stored vector is missing or dimension-mismatched, OR `force == True`). The indexer collects the document's `source_text` into the generation batch and, after the embedding returns, the service delegates to `repository.update_document(...)` which persists the complete document metadata, sets `embedding_status='ready'`, sets `activo=True`, clears `last_error`, and advances `fecha_ultima_modificacion`.
   - `created` is returned when no row exists: collect into the generation batch and, after the embedding returns, the service delegates to `repository.insert_document(...)`.
   - `--force` is passed explicitly to `create_or_update_document(...)` so the unchanged branch is bypassed for every applicable document.
5. After processing the builder's documents, scan every existing row for that presentation and:
   - if the row's `embedding_status` is `ready` or `failed` and the document tuple is not in the builder's output → `mark_stale`.

The indexer SHALL send `source_text` to the embedding client (NOT `normalized_text`) and SHALL reserve `normalized_text` for the deterministic hash comparison and `content_hash` computation. Source-text differences that produce the same `normalized_text` (and therefore the same `content_hash`) are deliberately treated as irrelevant for reindexing; the indexer does NOT claim that the embedding model is guaranteed to return the same vector for the same `normalized_text`.

#### Scenario: Indexer does not own commit / rollback / close / begin

- **WHEN** the indexer module is inspected
- **THEN** the module does NOT import or call `session.commit()`, `session.rollback()`, `session.close()`, or `session.begin()` anywhere in its source
- **AND** the indexer relies on the CLI for commit / rollback / close

#### Scenario: Unchanged ready document skips Ollama

- **WHEN** the indexer reconciles a presentation whose existing `canonical` row has the same `content_hash` as the builder's recomputed `canonical`, AND `embedding_status='ready'`, AND `activo=True`, AND the stored `vector` is present and dimension-valid, AND `force=False`
- **THEN** the embedding client is NOT called for that document
- **AND** the row's `vector`, `source_text`, `normalized_text`, `content_hash`, `embedding_status`, `activo`, `last_error`, and `fecha_ultima_modificacion` are unchanged
- **AND** no `flush()` is issued for that row
- **AND** the indexer does NOT claim that the embedding model is guaranteed to return the same vector for the same `normalized_text`; the unchanged decision is based solely on the 4.5 `content_hash` contract plus the status / activo / vector / force conditions

#### Scenario: Changed canonical triggers Ollama and updates the row

- **WHEN** the indexer reconciles a presentation whose `canonical` document's `content_hash` differs from the stored row
- **THEN** the embedding client receives `source_text` (not `normalized_text`) for the canonical document as part of a batch
- **AND** the service delegates to `repository.update_document(...)` so the row's complete document metadata (`source_text`, `normalized_text`, `content_hash`, `vector`) is persisted, `embedding_status='ready'`, `activo=True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced

#### Scenario: Missing document triggers Ollama and creates the row

- **WHEN** the indexer reconciles a presentation whose `alias` row for alias id 17 does not exist
- **THEN** the embedding client receives `source_text` for the alias document as part of a batch
- **AND** the service delegates to `repository.insert_document(...)` so a new row is inserted with `vector`, `source_text`, `normalized_text`, `content_hash`, `embedding_status='ready'`, `last_error=NULL`, `activo=True`

#### Scenario: Force flag overrides the unchanged branch

- **WHEN** the indexer runs with `force=True` for a presentation whose every ready document matches the stored `content_hash`, with `embedding_status='ready'`, `activo=True`, and a present, dimension-valid `vector`
- **THEN** the embedding client IS called for every applicable document
- **AND** the service delegates to `repository.update_document(...)` so every applicable document's complete document metadata is rewritten, `embedding_status='ready'`, `activo=True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced

#### Scenario: Failed / stale / inactive rows return to ready after successful regeneration

- **WHEN** the indexer reconciles a presentation whose existing row for a document tuple is currently `embedding_status='failed'`, `'stale'`, or `'inactive'`
- **THEN** the document is collected into the generation batch
- **AND** after the embedding returns, the service delegates to `repository.update_document(...)` so the row's complete document metadata is persisted, `embedding_status` transitions to `'ready'`, `activo` is set to `True`, `last_error` is cleared, and `fecha_ultima_modificacion` is advanced
- **AND** the indexer reports `updated` (not `created`) for each of the three transitions

#### Scenario: Embedding client failure marks every document in the batch failed

- **WHEN** the indexer batches N documents for a presentation and the embedding client raises `EmbeddingClientError` for the batch
- **THEN** the indexer calls `service.record_failed_document(document, error_message, *, modelo=settings.embedding_model)` for every document in the batch
- **AND** every document in the batch transitions to `embedding_status='failed'` with `last_error=<safe client message>` (sanitized; no source text, no vector values)
- **AND** for documents whose row already existed, the previous `vector` is preserved and `fecha_alta` is preserved
- **AND** for documents whose row did not exist, a new row is inserted with `vector=NULL`, `embedding_status='failed'`, `activo=True`, `last_error=<safe message>`, and the supplied `source_text` / `normalized_text` / `content_hash`
- **AND** the indexer increments only the `failed` counter for every affected document; it does NOT increment `created` or `updated`
- **AND** the indexer continues with the next safe batch (the next presentation's documents)

#### Scenario: Obsolete alias is marked stale

- **WHEN** the indexer reconciles a presentation whose previous alias list contained an alias id 17 that is no longer in the builder's output
- **THEN** the existing row for `(id_producto_presentacion, modelo, source_type='alias', source_record_id=17)` is transitioned to `embedding_status='stale'`
- **AND** the previous vector (when present) is preserved

#### Scenario: Inactive catalog chain is detected before embedding

- **WHEN** the indexer reconciles a presentation whose `Producto.activo=false`
- **THEN** the existing rows are loaded, every row transitions to `embedding_status='inactive'`
- **AND** the pure `ProductEmbeddingDocumentBuilder` is NOT run for that presentation
- **AND** the embedding client is NOT called for that presentation
- **AND** no new active rows are inserted for that presentation

#### Scenario: Reactivated catalog chain can be re-indexed

- **WHEN** a presentation was previously marked `inactive` and the parent chain becomes active again
- **THEN** a subsequent indexer run transitions the `inactive` rows through `service.create_or_update_document(...)` back to `ready` when the embedding succeeds

#### Scenario: Stale document can be re-indexed

- **WHEN** an `alias` row is currently `stale` and the builder starts producing that alias again
- **THEN** a subsequent indexer run transitions the row through `service.create_or_update_document(...)` back to `ready` when the embedding succeeds

#### Scenario: source_text is sent to the embedding client

- **WHEN** the indexer batches a presentation with two documents
- **THEN** the embedding client receives the `source_text` values (which preserve accents and casing) rather than the `normalized_text` values
- **AND** the deterministic `content_hash` comparison still uses `normalized_text`

### Requirement: Precise batching semantics

The indexer SHALL partition the documents requiring generation into batches whose size is bounded by `Settings.embedding_batch_size` (the per-run override when `--batch-size` is supplied, otherwise the loaded default). For each batch:

1. The indexer collects the `source_text` of every document in the batch.
2. The indexer calls `embedding_client.embed_documents(texts)` exactly once for this batch.
3. The returned vectors are mapped back to documents by position (`vectors[i]` corresponds to `documents[batch_offset + i]`).
4. For each `(document, vector)` pair, the indexer calls `service.create_or_update_document(document, vector, *, modelo=settings.embedding_model, force=force)`.
5. If `embed_documents` raises `EmbeddingClientError`, the indexer calls `service.record_failed_document(document, error_message, *, modelo=settings.embedding_model)` for every document in the failing batch. For each call: when no row exists, `repository.insert_document(...)` is invoked with `vector=NULL`, `embedding_status='failed'`, `activo=True`, and a sanitized `last_error`; when a row exists, `repository.update_document(...)` is invoked with the supplied metadata, `embedding_status='failed'`, `activo=True`, sanitized `last_error`, and the previous `vector` preserved. The indexer increments only the `failed` counter (never `created` or `updated`). No partial vector is written for the failed batch. The indexer continues with the next safe batch.

#### Scenario: Batch size matches the configured bound

- **WHEN** the indexer reconciles a presentation whose applicable documents exceed `Settings.embedding_batch_size`
- **THEN** the documents are split into sequential bounded batches of at most `Settings.embedding_batch_size`
- **AND** every batch follows the precise batching rules above

#### Scenario: Batch failure affects every document in the batch

- **WHEN** a batch's `embed_documents` call raises `EmbeddingConnectionError`
- **THEN** every document in the failing batch transitions to `failed`
- **AND** documents in subsequent batches are processed normally

### Requirement: Seeder does not own transactions

The system SHALL provide a `ProductoPresentacionEmbeddingSeeder` that wraps the indexer and returns a `SeedingResult` carrying `(created, updated, unchanged, stale, inactive, failed)` aggregate counts plus a per-presentation `SeedingOutcome` list. The seeder SHALL NOT call `session.commit()`, `session.rollback()`, or `session.close()`. The CLI is the only owner of those calls. The seeder's `dry_run=True` mode is strictly read-only: it projects the catalog, classifies every document through the same hash-based idempotency path, classifies the planned `stale` and `inactive` outcomes, and returns the same `SeedingResult` shape WITHOUT calling `mark_stale`, `mark_inactive`, `embed_documents`, `flush`, or `commit`, and WITHOUT inserting or updating rows.

#### Scenario: Seeder aggregates per-presentation outcomes

- **WHEN** the seeder reconciles three presentations producing `(2 created, 1 updated, 4 unchanged, 1 stale, 0 inactive, 0 failed)` documents
- **THEN** the `SeedingResult` aggregate matches `(created=2, updated=1, unchanged=4, stale=1, inactive=0, failed=0)`
- **AND** the per-presentation `SeedingOutcome` list exposes the document-level breakdown

#### Scenario: Seeder does not call commit / rollback / close

- **WHEN** the seeder module is inspected
- **THEN** the module does NOT import or call `session.commit()`, `session.rollback()`, or `session.close()` anywhere in its source

#### Scenario: Dry-run reports planned stale and inactive outcomes without persisting them

- **WHEN** the seeder runs with `dry_run=True` against a catalog where one presentation has an obsolete alias and another has an inactive `Producto`
- **THEN** the `SeedingResult` aggregate reports `stale=N` and `inactive=M` based on data-side classification only
- **AND** `service.mark_stale(row)` is NOT called
- **AND** `service.mark_inactive(row)` is NOT called
- **AND** the underlying rows in `producto_presentacion_embeddings` remain unchanged

### Requirement: CLI runner with commerce / producto / presentation filters

The system SHALL provide a CLI entry point at `backend/scripts/seed_product_presentation_embeddings.py` that opens a `_SessionLocal()` session, instantiates the indexer with the project's loaded `Settings` and an `OllamaEmbeddingClient(settings)` (the client's constructor is `(settings, transport=None, clock=None)`; it is NOT modified), calls `seeder.run(session)`, and prints a summary. The CLI SHALL accept the following flags:

- `--comercio-id <int>` — restrict the run to presentations of the given comercio.
- `--producto-id <int>` — restrict the run to presentations of the given producto.
- `--producto-presentacion-id <int>` — restrict the run to the given producto_presentacion.
- `--force` — bypass the unchanged branch for applicable documents.
- `--dry-run` — project the catalog and print the planned summary without calling Ollama, persisting, or committing.
- `--batch-size <int>` — override the embedding client's batch size for this run.

When `--batch-size` is supplied, the CLI SHALL call `dataclasses.replace(settings, embedding_batch_size=args.batch_size)` and pass the resulting frozen `Settings` to `OllamaEmbeddingClient(settings)`. The persisted `Settings` is unchanged; the override applies only to this run. `--batch-size 0` or negative values are rejected by argparse before any construction happens.

The CLI SHALL print a summary line `model=<embedding_model> dim=<embedding_dimension> created=<n> updated=<n> unchanged=<n> stale=<n> inactive=<n> failed=<n> elapsed=<seconds>s`, plus a per-presentation report `id_producto_presentacion=<id> status=<status> reason=<reason>`. The CLI SHALL exit `0` when `--dry-run` is supplied, when `failed=0` in a real run, or when the run is otherwise successful; the CLI SHALL exit `1` when `failed>0` in a real run or when an unhandled exception escapes.

The CLI owns `session.commit()`, `session.rollback()`, and `session.close()`. The structure mirrors `backend/scripts/seed_product_aliases.py`:

```python
session = _SessionLocal()
try:
    result = seeder.run(session)
    session.commit()
except Exception:
    session.rollback()
    raise
finally:
    session.close()
```

#### Scenario: CLI accepts the six required flags

- **WHEN** `python -m backend.scripts.seed_product_presentation_embeddings --help` is run
- **THEN** the help text lists `--comercio-id`, `--producto-id`, `--producto-presentacion-id`, `--force`, `--dry-run`, and `--batch-size`

#### Scenario: Default run prints summary and exits 0

- **WHEN** the CLI runs without flags against a clean catalog and the embedding client returns valid vectors
- **THEN** the CLI prints the summary line with the six required counters and exits `0`

#### Scenario: Run with failures prints summary and exits 1

- **WHEN** the CLI runs and two documents fail because the embedding client raises `EmbeddingConnectionError`
- **THEN** the CLI prints the summary line with `failed=2` and exits `1`

#### Scenario: Dry-run does not call Ollama, persist, or commit

- **WHEN** the CLI runs with `--dry-run`
- **THEN** the embedding client is NOT called
- **AND** no `INSERT` / `UPDATE` is issued against `producto_presentacion_embeddings`
- **AND** `service.mark_stale(row)` is NOT called
- **AND** `service.mark_inactive(row)` is NOT called
- **AND** `session.flush()` is NOT called
- **AND** `session.commit()` is NOT called
- **AND** the summary line still prints the six required counters based on data-side classification only

#### Scenario: Force overrides the unchanged branch

- **WHEN** the CLI runs with `--force` against a catalog whose every ready document already matches the stored `content_hash`
- **THEN** the embedding client IS called for every applicable document
- **AND** the summary line reports the resulting `created` / `updated` counts (the `unchanged` count is reduced accordingly)

#### Scenario: Batch-size overrides the embedding client's default through dataclasses.replace

- **WHEN** the CLI runs with `--batch-size 16`
- **THEN** the CLI calls `dataclasses.replace(settings, embedding_batch_size=16)` and the resulting frozen `Settings` is passed to `OllamaEmbeddingClient(settings)`
- **AND** the override applies only to this run; the persisted `Settings.embedding_batch_size` is unchanged
- **AND** the embedding client constructor is NOT modified — it still takes `(settings, transport=None, clock=None)`

#### Scenario: Batch-size of zero or negative is rejected

- **WHEN** the CLI runs with `--batch-size 0` or `--batch-size -1`
- **THEN** argparse rejects the value with a clear error before any construction happens
- **AND** the embedding client is NOT instantiated

#### Scenario: Commerce filter narrows the run

- **WHEN** the CLI runs with `--comercio-id 1`
- **THEN** the projection returns only the presentations of comercio 1
- **AND** inactive presentations of comercio 1 are included in the run
- **AND** presentations of other comercios are NOT loaded

#### Scenario: Combined filters compose

- **WHEN** the CLI runs with `--comercio-id 1 --producto-id 7`
- **THEN** the projection returns only the presentations of product 7 in comercio 1
- **AND** inactive presentations of product 7 in comercio 1 are NOT silently dropped

### Requirement: Dry-run failed scope is data-side only

The `dry_run.failed` counter SHALL count ONLY data-side failures (catalog projection errors, `InvalidProductEmbeddingDocument`, stored-vector dimension mismatch detected during read). It SHALL NOT include Ollama-side failures because Ollama is not called during `--dry-run`. The classification for `created`, `updated`, `unchanged`, `stale`, `inactive` follows the same code path the real run uses; only the write step and the Ollama call are omitted.

#### Scenario: Dry-run cannot predict Ollama failures

- **WHEN** the CLI runs with `--dry-run` against a catalog where a real run would fail because Ollama is unreachable
- **THEN** the summary line reports `failed=0` (no Ollama-side failures can be predicted)
- **AND** the per-presentation outcomes still classify the documents through the same hash-based idempotency path

#### Scenario: Dry-run records data-side failures

- **WHEN** the CLI runs with `--dry-run` against a catalog where one presentation has both `presentacion_codigo` and `presentacion_descripcion` empty
- **THEN** the pure builder raises `InvalidProductEmbeddingDocument` for that presentation
- **AND** the summary line records that presentation as `failed` with the builder's reason
- **AND** the rest of the catalog is still classified

### Requirement: Failure handling does not abort the run

The indexer SHALL catch per-document, per-batch, and per-presentation exceptions and translate them into typed outcomes without aborting the run. The CLI SHALL continue running through every presentation in scope, increment the `failed` counter for every failure, and exit with a non-zero status when `failed>0`.

#### Scenario: Embedding client batch timeout becomes multiple failed documents

- **WHEN** the indexer batches N documents for a presentation and the embedding client raises `EmbeddingTimeoutError`
- **THEN** every document in the batch transitions to `failed` with `last_error=<safe client message>`
- **AND** the indexer continues with the next presentation

#### Scenario: Pure builder validation error becomes a failed presentation

- **WHEN** the pure builder raises `InvalidProductEmbeddingDocument` for a presentation
- **THEN** the presentation is reported as `failed` with the builder's reason
- **AND** the indexer continues with the next presentation
- **AND** in `--dry-run` mode, this counts toward `dry_run.failed` (data-side failure)