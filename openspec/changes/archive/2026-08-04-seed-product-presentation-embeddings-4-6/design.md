## Context

Phase 4 has shipped:

- **4.1** — frozen product recognizer contract and baseline dataset.
- **4.2** — `ProductoAliasService` + `ProductoAlias` table; aliases carry `id_producto_presentacion IS NULL` (product-wide) vs non-null (presentation-specific) and a persisted `alias_normalizado`.
- **4.3** — `ProductoPresentacionEmbedding` table on `pgvector`, `ProductoPresentacionEmbeddingService` with `create_or_update` keyed by `(id_producto_presentacion, modelo)`, dimension enforcement, and the existing unique constraint `producto_presentacion_embedding_unico`.
- **4.4** — `EmbeddingClientProtocol`, `OllamaEmbeddingClient(settings, transport=None, clock=None)` (the constructor takes only `settings`, `transport`, and `clock` — no `batch_size` argument), and the `EmbeddingClientError` hierarchy. Settings (`embedding_url`, `embedding_model`, `embedding_timeout_seconds`, `embedding_batch_size`, `embedding_dimension`) live on the frozen `Settings` dataclass.
- **4.5** — pure `ProductEmbeddingDocumentBuilder` in `backend/embeddings/`; deterministic `canonical` / `description` / `alias` / `combined` documents; `normalize_for_embedding`; SHA-256 `content_hash` over `(producto_presentacion_id, source_type, source_record_id, normalized_text)`. The 4.5 hash contract guarantees that two builder invocations with the same `(producto_presentacion_id, source_type, source_record_id, normalized_text)` always produce the same `content_hash`; it does NOT guarantee that the embedding model returns the same vector for the same `normalized_text`.

The remaining gap is the persistence evolution. The current schema collapses every document of a presentation into one row keyed by `(id_producto_presentacion, modelo)`. That aggregate identity is wrong for the indexer because:

1. The builder emits one canonical, one optional description, N aliases, and one combined per presentation. Storing one vector hides which document the vector represents.
2. A renamed product name must invalidate the `canonical` and `combined` rows but leave the alias rows untouched. Today every document change forces re-embedding the whole presentation.
3. A deleted alias must leave a `stale` row (audit + revert) instead of disappearing.
4. An inactive `ProductoPresentacion` must keep its history as `inactive` instead of being filtered out.
5. Re-runs must skip Ollama for unchanged documents via `content_hash` comparison.
6. A re-activated catalog row must allow `inactive → ready`; a regenerated obsolete document must allow `stale → ready`; a recovered failure must allow `failed → ready`. None of these transitions are possible today.
7. The future hybrid recognizer needs to query one document at a time and needs `(id_producto_presentacion, source_type, source_record_id)` as a key.

This subphase must therefore evolve the persistence boundary to per-document rows with a reactivation-friendly state machine. The pure builder, the Ollama client (including its constructor signature), the alias service, and the recognizer remain untouched. A new indexer service consumes their public surfaces and persists per-document rows through a refactored repository / service pair. A new CLI runner is the only entry point and owns the outer transaction.

## Goals / Non-Goals

**Goals:**

- Evolve `producto_presentacion_embeddings` to per-document rows with the columns and constraints listed in the proposal.
- Replace the aggregate `(id_producto_presentacion, modelo)` uniqueness rule with two PostgreSQL partial unique indexes (one for `source_record_id IS NULL`, one for `source_record_id IS NOT NULL`).
- Make `vector` nullable (non-ready states may not have a vector).
- Add seven table-level `CHECK` constraints: `source_type_chk` (membership); `source_record_id_alias_chk` (alias / non-alias `source_record_id` rule); `ready_vector_chk` (the `ready → vector not null` rule); `content_hash_chk` (the lowercase 64-character hex `content_hash` format); `source_text_nonempty_chk` and `normalized_text_nonempty_chk` (the non-empty `source_text` / `normalized_text` rule); and `embedding_status_chk` (`embedding_status IN ('pending','ready','failed','stale','inactive')`).
- Persist every semantic document produced by the existing builder; never aggregate into one vector.
- Define `EmbeddingStatus` as `str, enum.Enum` whose values ARE the lowercase strings, store in a `String(32)` column, and enforce the closed set with a `CHECK`. One consistent database representation across Python and PostgreSQL.
- Hash-based idempotency at document level: the service returns `unchanged` only when ALL of the following hold — the stored `content_hash` matches the incoming `content_hash`, `embedding_status == 'ready'`, `activo == True`, the stored `vector` is present and dimension-valid, and `force == False`; otherwise a successfully generated document returns `updated` (or `created` when no row exists). The `--force` flag bypasses the unchanged branch for applicable documents. The reconciliation decision lives in the service or indexer, NOT in the repository. The repository performs only SQLAlchemy reads and writes (`update_document(...)` persists the complete document metadata; the service decides which fields to write).
- Status state machine with the authoritative reactivation paths: `pending → ready | failed | inactive`, `ready → failed | stale | inactive` (and `ready → ready` is an idempotent no-op), `failed → ready | failed | stale | inactive`, `stale → ready | failed | inactive`, `inactive → ready | failed | stale`. Any other transition is rejected with `InvalidEmbeddingStatusTransition`. `stale` and `inactive` are NOT permanently terminal.
- Preserve removed / obsolete documents as `stale` rather than deleting them.
- Preserve embeddings belonging to inactive catalog records as `inactive` rather than deleting them.
- Inactive-catalog detection happens BEFORE embedding: the indexer loads the existing rows, marks them inactive, and never runs the pure builder, never calls Ollama, and never inserts new active rows for the inactive presentation.
- Load every applicable `producto_presentacion` regardless of `activo` so the indexer can reconcile the whole catalog.
- Commerce / producto / producto_presentacion CLI filters that narrow the scope but never silently drop inactive rows within the narrowed scope.
- Repositories and services MUST NOT call `commit`, `rollback`, `close`, or `begin`. The CLI is the only place that calls `session.commit()` / `session.rollback()` / `session.close()`. SQLAlchemy `flush()` is permitted (it does not commit).
- Send `source_text` to the embedding client; reserve `normalized_text` for the deterministic hash comparison and `content_hash` computation. Source-text differences that produce the same `normalized_text` are deliberately treated as irrelevant for reindexing (matching `content_hash` → `unchanged`, no Ollama call). The indexer does NOT claim that the embedding model is guaranteed to return the same vector for the same `normalized_text`.
- Batching is precise: collect every document requiring generation for one batch, call `embed_documents` once for that batch, preserve positional mapping by index; if the batch raises `EmbeddingClientError`, every affected document transitions to `failed` with `last_error=<safe client message>` and the indexer continues with the next safe batch.
- CLI flags: `--comercio-id`, `--producto-id`, `--producto-presentacion-id`, `--force`, `--dry-run`, `--batch-size`.
- `--batch-size` is implemented with `dataclasses.replace(settings, embedding_batch_size=args.batch_size)` and the resulting frozen `Settings` is passed to `OllamaEmbeddingClient(settings)`. The client's constructor is NOT modified.
- `--dry-run` is strictly read-only. It classifies planned `(created, updated, unchanged, stale, inactive)` outcomes based on data-side classification only; it does NOT call `mark_stale`, does NOT call `mark_inactive`, does NOT insert / update / mark rows, does NOT call `flush()`, does NOT call `embed_documents` (Ollama is never reached), and does NOT call `session.commit()`. `dry_run.failed` counts ONLY projection, builder, or data-validation failures (catalog projection errors, `InvalidProductEmbeddingDocument`, stored-vector dimension mismatch detected during read). It CANNOT predict Ollama failures because Ollama is not called.
- Report fields: `created`, `updated`, `unchanged`, `stale`, `inactive`, `failed`.
- Minimum tests: migration integrity, document-level uniqueness, initial indexing, hash-based idempotency, semantic updates, alias stale / inactive behavior, failure handling, commerce isolation, dry-run behavior, plus the directly affected 4.3 persistence tests, existing 4.4 embedding-client tests, and existing 4.5 builder / normalization tests. No `api_smoke.py` full run, no unrelated fuzzy-recognizer suites.

**Non-Goals:**

- Vector similarity search, semantic ranking, hybrid scoring, or any recognizer integration (Subphase 4.7+).
- HNSW or IVFFlat index, `vector_cosine_ops`, or any pgvector index beyond the implicit table scan.
- Admin HTTP endpoint, background scheduler, or automatic catalog-change hook.
- Hybrid recognizer wiring, fuzzy recognizer changes, or any new recognizer subphase.
- Subphase 4.7 work.
- Modifying the `OllamaEmbeddingClient` constructor signature.
- Changing the recognizer, the alias service, the embedding client, the pure builder, or any Phase 1/2/3 module.

## Decisions

### Decision: Evolve the table, do not create a new one

The existing `producto_presentacion_embeddings` table is the persistence boundary; evolving it keeps the FK `ProductoPresentacion.embeddings` intact, keeps the cascade delete behavior intact, and avoids a one-time data migration that would otherwise be required to copy rows to a new table. The migration is hand-written in a single transaction with one explicit strategy for the placeholder dev/test rows from Subphase 4.3: `TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY`. There is NO pointless backfill-then-truncate cycle. The truncation is documented in the migration docstring as dev/test-only (the placeholder rows have no `source_type`, no `source_text`, no `content_hash` and cannot be reconciled into per-document rows; this matches the Subphase 2.13 precedent).

### Decision: Two partial unique indexes, not one

PostgreSQL treats `NULL` as distinct in standard unique constraints, so `(id_producto_presentacion, modelo, source_type, source_record_id)` UNIQUE alone does NOT enforce "at most one canonical per presentation per model" because all canonical rows would have `source_record_id IS NULL`. Two partial indexes are the smallest correct enforcement:

1. `uq_embedding_doc_null_source ON producto_presentacion_embeddings (id_producto_presentacion, modelo, source_type) WHERE source_record_id IS NULL` — covers canonical, description, and combined (one slot each per presentation per model).
2. `uq_embedding_doc_alias ON producto_presentacion_embeddings (id_producto_presentacion, modelo, source_type, source_record_id) WHERE source_record_id IS NOT NULL` — covers alias rows (one slot per alias per presentation per model).

### Decision: `vector` is nullable because non-ready states have no vector

`pending`, `failed`, `stale`, and `inactive` rows may exist without a vector. The dimension is still validated at insert / update time, but the column allows `NULL`. The pgvector `VECTOR(d)` type accepts `NULL`; the column simply becomes `nullable=True`. The `ready → vector not null` rule is enforced by a table-level `CHECK` so a `ready` row cannot be inserted with `vector IS NULL`.

### Decision: `EmbeddingStatus` is `str, enum.Enum` with lowercase values

The cleanest path is one consistent database representation:

```python
class EmbeddingStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    INACTIVE = "inactive"
```

- The Python value IS the lowercase string (`EmbeddingStatus.READY == "ready"`).
- The column is `String(32)`, not `SQLAlchemy Enum(...)`.
- The table-level `CHECK (embedding_status IN ('pending','ready','failed','stale','inactive'))` enforces the closed set.
- No `values_callable` shim, no `CREATE TYPE` in PostgreSQL, no uppercase-to-lowercase translation, no inconsistency between the Python enum and the DB check.

`mark_status(row, new_status)` validates the transition and writes `row.embedding_status = new_status.value`. SQLAlchemy stores the lowercase string; reading the column yields the same string; `EmbeddingStatus(value)` round-trips correctly.

### Decision: Status state machine with reactivation paths

Allowed transitions (everything else is rejected with `InvalidEmbeddingStatusTransition`; `ready → ready` is an idempotent no-op):

| From       | To                                          |
|------------|---------------------------------------------|
| `pending`  | `ready`, `failed`, `inactive`               |
| `ready`    | `failed`, `stale`, `inactive`               |
| `failed`   | `ready`, `failed`, `stale`, `inactive`      |
| `stale`    | `ready`, `failed`, `inactive`               |
| `inactive` | `ready`, `failed`, `stale`                  |

Key consequences:

- `stale → ready` is allowed. When a previously-deleted alias is re-added and the builder starts producing the document again, the indexer can re-embed and transition the row back to `ready`.
- `inactive → ready` is allowed. When the catalog is re-activated, the indexer can re-embed and transition the row back to `ready`.
- `failed → ready` is allowed. A retry that succeeds moves the row back to `ready` and clears `last_error`.
- `pending` is the only true "still generating" state; it can resolve to `ready` or `failed` once generation completes, or to `inactive` if the catalog becomes inactive before the document is generated. `pending → stale` is forbidden — a not-yet-generated document must finish generation before it can be preserved as obsolete.

`mark_status(row, new_status)` returns `True` on success and raises `InvalidEmbeddingStatusTransition` on illegal transitions. SQLAlchemy `flush()` follows to persist the new value.

### Decision: Hash-based idempotency lives in the service, not the repository

`ProductoPresentacionEmbeddingService.create_or_update_document(document, vector, *, modelo, force=False) -> DocumentReconciliationOutcome`:

1. Loads the existing row by `(id_producto_presentacion, modelo, source_type, source_record_id)`.
2. If no row exists → calls `repository.insert_document(...)` → returns `DocumentReconciliationOutcome.CREATED`.
3. If a row exists AND ALL of these are true: `row.content_hash == document.content_hash`; `row.embedding_status == 'ready'`; `row.activo == True`; `row.vector` is present and has the configured dimension; `force == False`. → returns `DocumentReconciliationOutcome.UNCHANGED`. No write. No Ollama call. No `fecha_ultima_modificacion` advance. No `flush()` call for that row.
4. Otherwise, when a row exists (the unchanged conditions failed — hashes differ, OR status is `failed` / `stale` / `inactive`, OR `activo` is `False`, OR the stored vector is missing / dimension-mismatched, OR `force == True`) → calls `repository.update_document(row, *, source_text=document.source_text, normalized_text=document.normalized_text, content_hash=document.content_hash, vector=vector, embedding_status=EmbeddingStatus.READY, activo=True, last_error=None)` → returns `DocumentReconciliationOutcome.UPDATED`. This path covers `failed → ready`, `stale → ready`, `inactive → ready`, and `--force` with an unchanged hash.

`ProductoPresentacionEmbeddingService.record_failed_document(document, error_message, *, modelo)` handles embedding failures. Required behavior:

- when no row exists for the document tuple → calls `repository.insert_document(...)` with `vector=NULL`, `embedding_status='failed'`, `activo=True`, and a sanitized `last_error` derived from `error_message`;
- when a row exists → calls `repository.update_document(row, *, source_text=document.source_text, normalized_text=document.normalized_text, content_hash=document.content_hash, vector=row.vector, embedding_status=EmbeddingStatus.FAILED, activo=True, last_error=sanitized_error_message)` — the previous `vector` and `fecha_alta` are preserved;
- the operation only records the failure; the indexer increments only the `failed` counter, never `created` or `updated`;
- a batch failure applies `record_failed_document(...)` to every affected document in the batch.

The repository methods are pure SQLAlchemy reads and writes (`insert_document`, `update_document`, `find_by_document`, `list_*`, `mark_status`). No hash comparison, no reconciliation logic, no commit, no rollback, no close, no begin.

### Decision: `--batch-size` is applied through `dataclasses.replace`

The current `OllamaEmbeddingClient.__init__(settings, transport=None, clock=None)` does NOT take a `batch_size` argument. The CLI's `--batch-size` is applied without changing the client: when the flag is supplied, the CLI calls `dataclasses.replace(settings, embedding_batch_size=args.batch_size)` and passes the resulting frozen `Settings` to `OllamaEmbeddingClient(settings)`. The persisted `Settings` is untouched; the override applies only to this run. `--batch-size 0` or negative values are rejected by argparse before any construction happens.

### Decision: Inactive-catalog detection happens before embedding

For each presentation, the indexer inspects the parent chain `Producto.activo`, `CategoriaProducto.activo`, `Presentacion.activo`, `ProductoPresentacion.activo` first. If any is `false`, the indexer:

1. Calls `service.list_by_producto_presentacion_and_model(...)` to load the existing rows.
2. Calls `service.mark_inactive(row)` for every row (any non-terminal state → `inactive`).
3. Does NOT run the pure `ProductEmbeddingDocumentBuilder`.
4. Does NOT call `embed_documents`.
5. Does NOT insert new active rows.

If the chain is active, the indexer proceeds with the normal builder → hash-idempotency → batched-embedding → status-transition flow.

### Decision: Batching semantics

The indexer partitions the documents requiring generation into batches of `Settings.embedding_batch_size` (the per-run value if `--batch-size` was supplied, otherwise the loaded default). For each batch:

1. The indexer collects the `source_text` of every document in the batch.
2. The indexer calls `embedding_client.embed_documents(texts)` exactly once (skipped entirely when `dry_run=True`).
3. The returned vectors are mapped back to documents by position (`vectors[i]` corresponds to `documents[batch_offset + i]`).
4. For each `(document, vector)` pair, the indexer calls `service.create_or_update_document(document, vector, *, modelo=settings.embedding_model, force=force)`.
5. If `embed_documents` raises `EmbeddingClientError` for the batch, the indexer calls `service.record_failed_document(document, error_message, *, modelo=settings.embedding_model)` for EVERY document in the failing batch. The service applies the operation per document: missing rows are inserted with `vector=NULL`, `embedding_status='failed'`, `activo=True`, and a sanitized `last_error`; existing rows are updated with the document metadata, `embedding_status='failed'`, `activo=True`, sanitized `last_error`, while preserving the previous `vector` and `fecha_alta`. The indexer increments only the `failed` counter (never `created` or `updated`). No partial vector is written for the failed batch. The indexer continues with the next safe batch (the next presentation's documents).

### Decision: Repository only does reads and writes

The repository surface is intentionally narrow:

- `find_by_document(id_pp, modelo, source_type, source_record_id) -> Row | None`
- `list_by_producto_presentacion_and_model(id_pp, modelo) -> list[Row]`
- `list_by_producto_presentacion(id_pp) -> list[Row]`
- `list_by_producto(id_producto, modelo) -> list[Row]`
- `list_by_comercio(id_comercio, modelo) -> list[Row]`
- `insert_document(...) -> Row`
- `update_document(row, *, source_text, normalized_text, content_hash, vector, embedding_status, activo, last_error) -> Row` — persists the complete document metadata (`source_text`, `normalized_text`, `content_hash`, `vector`, `embedding_status`, `activo`, `last_error`) and advances `fecha_ultima_modificacion`. The repository applies only the write; reconciliation decisions remain in the service / indexer.
- `mark_status(row, new_status) -> Row`

No hash comparison, no decision logic, no commit / rollback / close / begin. SQLAlchemy `flush()` is permitted (no commit). The service and indexer own the decision logic; the repository owns SQLAlchemy.

### Decision: `dry_run` is strictly read-only

`--dry-run` projects the catalog and classifies every document through the same hash-based idempotency path the real run uses, but performs NO writes, NO `flush()`, NO `embed_documents` calls, and NO `session.commit()`. When `dry_run=True`:

- planned `created`, `updated`, `unchanged` totals are classified through the same service path (without actually persisting any update or insert);
- planned `stale` and `inactive` outcomes are also classified and counted, so the summary reports them;
- `service.mark_stale(row)` is NOT called (planned stale documents are counted but not written);
- `service.mark_inactive(row)` is NOT called (planned inactive documents are counted but not written);
- `repository.insert_document(...)`, `repository.update_document(...)`, and `repository.mark_status(...)` are NOT called;
- `session.flush()` is NOT called;
- `embedding_client.embed_documents(...)` is NOT called — Ollama is never reached;
- `session.commit()` is NOT called; the session is closed in the `finally` block without a prior commit.

The `failed` counter in a dry run therefore CANNOT include Ollama-side failures. It includes only:

- `ProductoEmbeddingCatalogProjection` failures (e.g. the projection repository raises on a malformed join result).
- `InvalidProductEmbeddingDocument` raised by the pure builder (e.g. missing presentation data).
- Stored-vector dimension mismatches detected while reading existing rows (`vector` length differs from `Settings.embedding_dimension`).

A successful dry run reports `failed=0`. The dry-run classifier uses the same code path as the real run for every other classification (`created`, `updated`, `unchanged`, `stale`, `inactive`); only the write step, the Ollama call, and the commit are omitted.

### Decision: Stale vs inactive are both preservable, both reactivatable

- `stale` — the builder no longer produces this document (alias deleted, source_type no longer emitted). The vector, when present, is preserved. Reactivation (`stale → ready`) is allowed when the document becomes generated again.
- `inactive` — the parent catalog chain is inactive (`ProductoPresentacion.activo = false`, or any parent). The vector, when present, is preserved. Reactivation (`inactive → ready`) is allowed when the catalog is re-activated.

Both are reported separately in the run summary. The CLI counts `stale` documents as "documents marked stale this run" (only those that flipped `ready | failed → stale` during this run; pre-existing stale rows are not counted again) and `inactive` documents as "documents marked inactive this run" (only those that flipped `ready | failed → inactive` during this run).

### Decision: CLI owns commit / rollback / close

The CLI is the only owner of `session.commit()`, `session.rollback()`, and `session.close()`. The seeder does NOT call them. The indexer does NOT call them. The repository does NOT call them. The service does NOT call them. SQLAlchemy `flush()` is permitted (it writes rows to the session's pending state without committing).

Transaction behavior at the CLI:

- a completed real run with recoverable embedding failures persists the `failed` rows (with sanitized `last_error`), commits once via `session.commit()`, and exits with code `1`. The run is treated as successful from a persistence standpoint; the non-zero exit code surfaces the recoverable failures to the operator.
- a run whose failure is an unhandled persistence or integrity error (e.g. `SQLAlchemyError`, `IntegrityError` not translated to `DuplicateEmbeddingDocument`) does NOT commit; the CLI calls `session.rollback()` once, re-raises the exception, and exits with code `1`.
- a `--dry-run` never commits. The CLI opens the session, runs the projection and classification without persisting, closes the session in `finally`, and exits with code `0`.

The CLI's structure mirrors the project pattern (`backend/scripts/seed_product_aliases.py`):

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

The seeder's `run(session)` method is called exactly once with the outer-session argument.

### Decision: No new FastAPI surface

The CLI is the only entry point for Subphase 4.6. No new router, no new endpoint, no new Pydantic schema.

## Risks / Trade-offs

- **[Risk] Truncating the existing dev/test rows loses placeholder data** → Mitigation: the existing rows from Subphase 4.3 are placeholders with no `source_type`, no `source_text`, no `content_hash`; they are unusable for per-document indexing. The migration documents the truncation as dev/test-only.
- **[Risk] The state machine is permissive enough to allow unexpected transitions** → Mitigation: every transition is enumerated in the table above; `mark_status` validates against the table; `InvalidEmbeddingStatusTransition` is raised for anything outside.
- **[Risk] Two partial unique indexes add two DDL operations to the migration** → Accepted trade-off; partial indexes are the smallest correct enforcement for NULL `source_record_id`. The alternative (COALESCE expression index) loses introspection clarity.
- **[Risk] The hash-based idempotency branch could miss a semantic change** → The 4.5 hash contract guarantees `content_hash` equality whenever `(producto_presentacion_id, source_type, source_record_id, normalized_text)` is identical. Source-text differences that produce the same `normalized_text` are deliberately treated as irrelevant for reindexing (matching `content_hash` → `unchanged`, no Ollama call). The indexer does NOT claim that the embedding model is guaranteed to return the same vector for the same `normalized_text`; this is an explicit, deliberate choice documented in the proposal.
- **[Risk] A future embedding model change requires re-indexing every document** → Mitigation: `--force` regenerates applicable documents without changing the catalog; a future reindex subphase can use the same code path with `--force`.
- **[Risk] Partial index conflicts on concurrent runs** → Mitigation: the service catches `IntegrityError` on partial index conflicts and translates to `DuplicateEmbeddingDocument`; the run continues; the operator re-runs after the conflict resolves.
- **[Risk] Inactive catalog reconciliation grows the report** → Accepted; `inactive` is a first-class report field by design.
- **[Risk] `--batch-size` is forwarded through `dataclasses.replace`, not through a constructor argument** → Documented in the proposal and design; the embedding client constructor signature is unchanged.
- **[Risk] The pure builder raises `InvalidProductEmbeddingDocument` for a presentation** → Mitigation: the indexer catches it per presentation, increments `failed`, records the reason, and continues. In `--dry-run`, this counts toward `dry_run.failed` (data-side failure).
- **[Risk] Stale documents accumulate indefinitely** → Accepted for Subphase 4.6; cleanup is a future subphase.
- **[Risk] `dry_run.failed` understates real-run failure rates** → Documented as a deliberate limitation: dry runs cannot predict Ollama failures because Ollama is not called.

## Migration Plan

Hand-written Alembic migration in a single transaction. Applied to `supernova_test` first, then `supernova`. The migration is reversible: `downgrade()` is deterministic — it truncates `producto_presentacion_embeddings` BEFORE restoring the legacy `(id_producto_presentacion, modelo)` uniqueness rule and BEFORE restoring `vector NOT NULL` — and then drops the partial indexes, drops the `CHECK` constraints, drops the new columns, and restores the legacy `UniqueConstraint` and the `vector NOT NULL` rule.

Steps (one explicit strategy for legacy rows):

1. **Pre-migration check (informational):** count existing rows in `producto_presentacion_embeddings`; log the count.
2. **Add new columns nullable:** `source_type`, `source_record_id`, `source_text`, `normalized_text`, `content_hash`, `embedding_status` (`String(32)`, default `'pending'`), `activo` (`Boolean`, default `True`, server-default `"true"`), `last_error`.
3. **Truncate placeholder rows:** `TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY`. Documented as dev/test-only — no production data yet. Single explicit strategy; no backfill step.
4. **Drop the existing `UniqueConstraint`** named `producto_presentacion_embedding_unico`.
5. **Make `vector` nullable** (`ALTER COLUMN vector DROP NOT NULL`).
6. **Add seven table-level `CHECK` constraints:**
   - `source_type_chk`: `source_type IN ('canonical','description','alias','combined')`.
   - `source_record_id_alias_chk`: `(source_type = 'alias' AND source_record_id IS NOT NULL) OR (source_type <> 'alias' AND source_record_id IS NULL)`.
   - `ready_vector_chk`: `embedding_status <> 'ready' OR vector IS NOT NULL`.
   - `content_hash_chk`: `content_hash ~ '^[0-9a-f]{64}$'`.
   - `source_text_nonempty_chk`: `length(btrim(source_text)) > 0`.
   - `normalized_text_nonempty_chk`: `length(btrim(normalized_text)) > 0`.
   - `embedding_status_chk`: `embedding_status IN ('pending','ready','failed','stale','inactive')`.
7. **Create the two partial unique indexes.**
8. **Set NOT NULL** on `source_type`, `source_text`, `normalized_text`, `content_hash`.

`downgrade()` is deterministic and runs in this exact order: FIRST `TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY` (so the table is empty before any legacy-shape rule is restored), THEN drop the two partial unique indexes, drop the seven `CHECK` constraints, drop the new columns, restore the legacy `(id_producto_presentacion, modelo)` `UniqueConstraint`, and restore `vector` to `nullable=False`. The truncate MUST run BEFORE restoring the legacy uniqueness rule and BEFORE restoring `vector NOT NULL`, otherwise the legacy shape cannot be re-applied to rows that already satisfy the per-document shape.

The migration is added to `backend/alembic/env.py`'s import block (it already imports `ProductoPresentacionEmbedding`; no change required) and applied to both databases with the standard project commands:

```
PYTHONPATH=. venv/bin/alembic upgrade head                                    # supernova_test
SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova \
    PYTHONPATH=. venv/bin/alembic upgrade head                                # supernova
```

No FastAPI surface change. The CLI is the entry point. Rollback is `alembic downgrade -1` followed by re-running the Subphase 4.3 migration if needed.

The OpenSpec change remains active after `/opsx:apply`; sync and archive are explicit user commands per the project's workflow rule.

## Open Questions

None. The wiring is fully specified by the proposal, the corrected schema evolution, the reactivation-friendly state machine, the explicit batching semantics, the inactive-first detection rule, the `dry_run.failed` scope, the `--batch-size` implementation through `dataclasses.replace`, the existing 4.1–4.5 specs, and the existing services / repositories / settings modules.