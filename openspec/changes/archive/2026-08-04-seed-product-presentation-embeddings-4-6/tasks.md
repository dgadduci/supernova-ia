## 1. Schema migration (single explicit strategy)

- [x] 1.1 Create `backend/alembic/versions/<rev>_evolve_producto_presentacion_embeddings_to_per_document.py` with `down_revision = "a7c9e1f2b3d4"`. Hand-written single transaction.
- [x] 1.2 Add new columns nullable initially: `source_type String(32)`, `source_record_id Integer`, `source_text Text`, `normalized_text Text`, `content_hash String(64)`, `embedding_status String(32)` (default `'pending'`), `activo Boolean` (default `True`, server-default `"true"`), `last_error Text`.
- [x] 1.3 **Single explicit strategy**: `TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY`. No pointless backfill-then-truncate cycle. Document in the migration docstring as dev/test-only (placeholder rows from Subphase 4.3 have no `source_type`, no `source_text`, no `content_hash`, and cannot be reconciled into per-document rows; matches the Subphase 2.13 precedent).
- [x] 1.4 Drop `UniqueConstraint` `producto_presentacion_embedding_unico` (the legacy aggregate rule).
- [x] 1.5 Make `vector` nullable (`ALTER COLUMN vector DROP NOT NULL`).
- [x] 1.6 Add table-level `CheckConstraint`s (seven total):
  - `source_type_chk`: `source_type IN ('canonical','description','alias','combined')`.
  - `source_record_id_alias_chk`: `(source_type = 'alias' AND source_record_id IS NOT NULL) OR (source_type <> 'alias' AND source_record_id IS NULL)`.
  - `ready_vector_chk`: `embedding_status <> 'ready' OR vector IS NOT NULL`.
  - `content_hash_chk`: `content_hash ~ '^[0-9a-f]{64}$'`.
  - `source_text_nonempty_chk`: `length(btrim(source_text)) > 0`.
  - `normalized_text_nonempty_chk`: `length(btrim(normalized_text)) > 0`.
  - `embedding_status_chk`: `embedding_status IN ('pending','ready','failed','stale','inactive')`.
- [x] 1.7 Create partial unique index `uq_embedding_doc_null_source ON producto_presentacion_embeddings (id_producto_presentacion, modelo, source_type) WHERE source_record_id IS NULL`.
- [x] 1.8 Create partial unique index `uq_embedding_doc_alias ON producto_presentacion_embeddings (id_producto_presentacion, modelo, source_type, source_record_id) WHERE source_record_id IS NOT NULL`.
- [x] 1.9 Set NOT NULL on `source_type`, `source_text`, `normalized_text`, `content_hash`.
- [x] 1.10 Implement `downgrade()` that is deterministic: FIRST `TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY`, THEN drop the partial indexes, drop the `CHECK` constraints, drop the new columns, restore the legacy `UniqueConstraint`, and restore `vector` to `nullable=False`. The truncate must run BEFORE restoring the legacy `(id_producto_presentacion, modelo)` uniqueness rule and BEFORE restoring `vector NOT NULL`.
- [x] 1.11 Apply to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm with `alembic current` and `\d producto_presentacion_embeddings` in `psql`.

## 2. Model evolution

- [x] 2.1 In `backend/models/producto_presentacion_embedding.py`, define `class EmbeddingStatus(str, enum.Enum)` with values that ARE the lowercase strings: `PENDING = "pending"`, `READY = "ready"`, `FAILED = "failed"`, `STALE = "stale"`, `INACTIVE = "inactive"`. `EmbeddingStatus.READY == "ready"` is a true equality.
- [x] 2.2 Map the column as `String(32)` (NOT `SQLAlchemy Enum(...)`). The Python enum value matches the database string; the table-level `CHECK` enforces the closed set.
- [x] 2.3 Add columns: `source_type` (`String(32)`, nullable=False after migration), `source_record_id` (`Integer`, nullable), `source_text` (`Text`, nullable=False after migration), `normalized_text` (`Text`, nullable=False after migration), `content_hash` (`String(64)`, nullable=False after migration), `embedding_status` (`String(32)`, nullable=False, default=`EmbeddingStatus.PENDING.value` = `"pending"`), `activo` (`Boolean`, nullable=False, default=True, server-default="true"), `last_error` (`Text`, nullable).
- [x] 2.4 Change `vector` to `nullable=True`.
- [x] 2.5 Drop the legacy `UniqueConstraint("id_producto_presentacion", "modelo", name="producto_presentacion_embedding_unico")` from `__table_args__`.
- [x] 2.6 Add to `__table_args__`:
  - `Index("uq_embedding_doc_null_source", "id_producto_presentacion", "modelo", "source_type", unique=True, postgresql_where=text("source_record_id IS NULL"))`.
  - `Index("uq_embedding_doc_alias", "id_producto_presentacion", "modelo", "source_type", "source_record_id", unique=True, postgresql_where=text("source_record_id IS NOT NULL"))`.
  - `CheckConstraint("source_type IN ('canonical','description','alias','combined')", name="source_type_chk")`.
  - `CheckConstraint("(source_type = 'alias' AND source_record_id IS NOT NULL) OR (source_type <> 'alias' AND source_record_id IS NULL)", name="source_record_id_alias_chk")`.
  - `CheckConstraint("embedding_status <> 'ready' OR vector IS NOT NULL", name="ready_vector_chk")`.
  - `CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_chk")`.
  - `CheckConstraint("length(btrim(source_text)) > 0", name="source_text_nonempty_chk")`.
  - `CheckConstraint("length(btrim(normalized_text)) > 0", name="normalized_text_nonempty_chk")`.
  - `CheckConstraint("embedding_status IN ('pending','ready','failed','stale','inactive')", name="embedding_status_chk")`.
- [x] 2.7 Update `backend/models/__init__.py` to export `EmbeddingStatus`. Verify Alembic autogenerate no longer suggests drift after `alembic upgrade head`.

## 3. Exception surface

- [x] 3.1 In `backend/services/exceptions.py`, add `InvalidEmbeddingStatusTransition(ValueError)`, `DuplicateEmbeddingDocument`. Keep `EmbeddingNotFound` as a back-compat alias (now maps to a per-document lookup, not the aggregate identity).

## 4. Repository refactor (reads and writes only)

- [x] 4.1 In `backend/repositories/producto_presentacion_embedding_repository.py`, replace the aggregate surface with per-document methods.
- [x] 4.2 `find_by_document(id_producto_presentacion, modelo, source_type, source_record_id) -> ProductoPresentacionEmbedding | None` — pure SQLAlchemy read.
- [x] 4.3 `list_by_producto_presentacion_and_model(id_producto_presentacion, modelo) -> list[ProductoPresentacionEmbedding]` — pure SQLAlchemy read.
- [x] 4.4 `list_by_comercio(id_comercio, modelo) -> list[ProductoPresentacionEmbedding]` — pure SQLAlchemy read with explicit `joinedload`/`selectinload`. No N+1.
- [x] 4.5 `list_by_producto(id_producto, modelo) -> list[ProductoPresentacionEmbedding]` — pure SQLAlchemy read.
- [x] 4.6 `list_by_producto_presentacion(id_producto_presentacion) -> list[ProductoPresentacionEmbedding]` — pure SQLAlchemy read.
- [x] 4.7 `insert_document(...) -> ProductoPresentacionEmbedding` — pure SQLAlchemy insert with `flush()`. NO hash comparison, NO decision logic.
- [x] 4.8 `update_document(row, *, source_text, normalized_text, content_hash, vector, embedding_status, activo, last_error) -> ProductoPresentacionEmbedding` — pure SQLAlchemy update that persists the complete document metadata (`source_text`, `normalized_text`, `content_hash`, `vector`, `embedding_status`, `activo`, `last_error`) and advances `fecha_ultima_modificacion`. The repository applies only the write; reconciliation decisions remain in the service / indexer. NO hash comparison, NO reconciliation logic.
- [x] 4.9 `mark_status(row, new_status) -> ProductoPresentacionEmbedding` — pure SQLAlchemy update of `embedding_status` with `flush()`. The transition validation lives in the service (or indexer), NOT here.
- [x] 4.10 Keep the legacy aggregate methods (`get_by_identity`, `create_or_update(id_pp, vector, modelo)`, etc.) as deprecated wrappers that route to the per-document surface with `source_type='canonical', source_record_id=None`. The wrappers preserve the existing public surface for callers that have not migrated.
- [x] 4.11 Repository methods MUST NOT call `commit`, `rollback`, `close`, or `begin`. SQLAlchemy `flush()` is permitted (no commit).

## 5. Service refactor (hash comparison lives here)

- [x] 5.1 In `backend/services/producto_presentacion_embedding_service.py`, define `DocumentReconciliationOutcome = Literal["created", "updated", "unchanged"]`.
- [x] 5.2 Add `create_or_update_document(document, vector, *, modelo, force=False) -> DocumentReconciliationOutcome` that:
  1. calls `repository.find_by_document(id_producto_presentacion, modelo, source_type, source_record_id)`;
  2. if missing → calls `repository.insert_document(...)` → returns `"created"`;
  3. if a row exists AND ALL of the following are true: `row.content_hash == document.content_hash`, `row.embedding_status == 'ready'`, `row.activo == True`, `row.vector` is present and has the configured dimension, `force == False` → returns `"unchanged"` (no write, no Ollama call, no `flush()` for that row);
  4. otherwise (row exists but any unchanged condition failed) → calls `repository.update_document(row, *, source_text=document.source_text, normalized_text=document.normalized_text, content_hash=document.content_hash, vector=vector, embedding_status=EmbeddingStatus.READY, activo=True, last_error=None)` → returns `"updated"`. This path covers `failed → ready`, `stale → ready`, `inactive → ready`, and `--force` with an unchanged hash.
- [x] 5.3 Add `record_failed_document(document, error_message, *, modelo)` that records an embedding failure:
  1. if missing → calls `repository.insert_document(...)` with `vector=NULL`, `embedding_status='failed'`, `activo=True`, and a sanitized `last_error` derived from `error_message`;
  2. if a row exists → calls `repository.update_document(row, *, source_text=document.source_text, normalized_text=document.normalized_text, content_hash=document.content_hash, vector=row.vector, embedding_status=EmbeddingStatus.FAILED, activo=True, last_error=sanitized_error_message)` — the previous `vector` and `fecha_alta` are preserved;
  3. the operation never increments a successful `created` or `updated` counter at the indexer level; only the `failed` counter advances.
- [x] 5.4 Add `mark_status(row, new_status)` that validates the transition against the authoritative state-machine table (`pending → ready | failed | inactive`, `ready → failed | stale | inactive`, `failed → ready | failed | stale | inactive`, `stale → ready | failed | inactive`, `inactive → ready | failed | stale`; `ready → ready` is an idempotent no-op) and calls `repository.mark_status(row, new_status)`. Raises `InvalidEmbeddingStatusTransition` for forbidden transitions.
- [x] 5.5 Add `mark_stale(row)` (allowed transitions: `ready → stale`, `failed → stale`) and `mark_inactive(row)` (allowed transitions: `ready → inactive`, `failed → inactive`, `stale → inactive`, `pending → inactive`) as thin wrappers that call `mark_status`.
- [x] 5.6 Add `find_by_document(...)`, `list_by_producto_presentacion_and_model(...)`, `list_by_comercio(...)`, `list_by_producto(...)`, `list_by_producto_presentacion(...)` that wrap the repository methods.
- [x] 5.7 Service methods MUST NOT call `commit`, `rollback`, `close`, or `begin`. SQLAlchemy `flush()` is permitted.
- [x] 5.8 Keep the legacy aggregate methods as deprecated wrappers that route to the new per-document surface.

## 6. Indexer repository (commerce-scoped projection)

- [x] 6.1 Create `backend/repositories/producto_presentacion_embedding_index_repository.py` exporting `ProductoPresentacionEmbeddingIndexRepository(session)`.
- [x] 6.2 Add `list_presentations(*, id_comercio, id_producto, id_producto_presentacion) -> list[PresentationBundle]` that joins `ProductoPresentacion` × `Producto` × `CategoriaProducto` × `Presentacion`, eager-loads the applicable aliases through `Producto.aliases` filtered by `(ProductoAlias.activo.is_(True)) & ((ProductoAlias.id_producto_presentacion.is_(None)) | (ProductoAlias.id_producto_presentacion == ProductoPresentacion.id))`, and applies the optional filters. Active AND inactive presentations are returned (no `activo` filter on `ProductoPresentacion`).
- [x] 6.3 `PresentationBundle` is a `dataclass(frozen=True)` carrying the catalog projection DTOs, the applicable alias list, and the parent `activo` flags (`producto_activo`, `categoria_producto_activo`, `presentacion_activo`, `producto_presentacion_activo`) so the indexer can detect inactive catalog chains before any embedding work.
- [x] 6.4 Two-query strategy: one query for the projection rows (eager-loaded), one query for the alias map. No N+1.

## 7. Indexer service

- [x] 7.1 Create `backend/services/producto_presentacion_embedding_indexer.py` exporting `ProductoPresentacionEmbeddingIndexer(session, embedding_client, embedding_service, index_repository, settings)`. The indexer does NOT call `commit`, `rollback`, `close`, or `begin` anywhere.
- [x] 7.2 Implement `index_presentations(*, id_comercio=None, id_producto=None, id_producto_presentacion=None, force=False, dry_run=False) -> IndexingResult`. When `dry_run=True`, the indexer is strictly read-only: it classifies planned `created`, `updated`, `unchanged`, `stale`, and `inactive` outcomes, does NOT call `mark_stale` / `mark_inactive`, does NOT call `embed_documents`, does NOT call `repository.insert_document` / `update_document` / `mark_status`, does NOT call `flush()`, and does NOT commit; return the same `IndexingResult` shape based on classification only.
- [x] 7.3 For each presentation in the projection:
  1. Detect the inactive catalog chain FIRST. If `not (producto_activo and categoria_producto_activo and presentacion_activo and producto_presentacion_activo)`:
     - call `service.list_by_producto_presentacion_and_model(...)` to load the existing rows;
     - call `service.mark_inactive(row)` for every row (when `dry_run=False`);
     - do NOT run the pure `ProductEmbeddingDocumentBuilder`;
     - do NOT call `embed_documents`;
     - do NOT insert new active rows;
     - record the outcome as `inactive=<n>` for that presentation.
  2. If the chain is active, run the pure builder to obtain the deterministic documents.
- [x] 7.4 For each document from the builder:
  1. Look up the existing row through `service.find_by_document(...)`.
  2. If a row exists AND ALL of the following are true: `row.content_hash == document.content_hash`, `row.embedding_status == 'ready'`, `row.activo == True`, `row.vector` is present and has the configured dimension, `force == False` → record `unchanged`. Do NOT call Ollama, do NOT write, do NOT call `flush()`. The indexer does NOT claim that the embedding model is guaranteed to return the same vector for the same `normalized_text`.
  3. Otherwise → add the document's `source_text` to the generation batch. `modelo` and `force` are passed explicitly to `create_or_update_document(document, vector, *, modelo=settings.embedding_model, force=force)` later.
- [x] 7.5 After classifying every document for the presentation, scan every existing row for that presentation:
  - if the row's `embedding_status` is `ready` or `failed` and the document tuple is not in the builder's output → call `service.mark_stale(row)` (when `dry_run=False`).
- [x] 7.6 Send each generation batch to `embedding_client.embed_documents(texts)` exactly once (skipped entirely when `dry_run=True`). Map returned vectors back to documents by position (`vectors[i]` ↔ `documents[batch_offset + i]`). For each `(document, vector)` pair, call `service.create_or_update_document(document, vector, *, modelo=settings.embedding_model, force=force)` and record the outcome (`created` or `updated`).
- [x] 7.7 If `embed_documents` raises `EmbeddingClientError` for the batch, call `service.record_failed_document(document, error_message, *, modelo=settings.embedding_model)` for EVERY document in the failing batch. The service applies the operation per document: missing rows are inserted with `vector=NULL`, `embedding_status='failed'`, `activo=True`, and sanitized `last_error`; existing rows are updated with the document metadata, `embedding_status='failed'`, `activo=True`, sanitized `last_error`, while preserving the previous `vector` and `fecha_alta`. The indexer increments only the `failed` counter (never `created` or `updated`). Continue with the next safe batch.
- [x] 7.8 Aggregate per-document outcomes into per-presentation `IndexingOutcome(status, created, updated, unchanged, stale, inactive, failed)` and roll them up into `IndexingResult(completed, failed)`.

## 8. Seeder wrapper (no transactions)

- [x] 8.1 Create `backend/services/producto_presentacion_embedding_seeder.py` exporting `ProductoPresentacionEmbeddingSeeder(indexer)`, `SeedingResult`, `SeedingOutcome`.
- [x] 8.2 Implement `run(session, *, id_comercio=None, id_producto=None, id_producto_presentacion=None, force=False, dry_run=False) -> SeedingResult`. The seeder calls `indexer.index_presentations(...)` and aggregates `(created, updated, unchanged, stale, inactive, failed)` counters plus per-presentation outcomes.
- [x] 8.3 The seeder does NOT call `session.commit()`, `session.rollback()`, or `session.close()`. The CLI owns those calls. (Verified by `grep` over the seeder module.)

## 9. CLI runner (owns the outer transaction)

- [x] 9.1 Create `backend/scripts/seed_product_presentation_embeddings.py` with `main(argv: list[str] | None = None) -> int`.
- [x] 9.2 Parse `--comercio-id` (`int`), `--producto-id` (`int`), `--producto-presentacion-id` (`int`), `--force` (`store_true`), `--dry-run` (`store_true`), `--batch-size` (`int`).
- [x] 9.3 Open `_SessionLocal()`. Compute the effective settings:
  - `settings = load_settings()`;
  - when `args.batch_size` is not `None`, call `dataclasses.replace(settings, embedding_batch_size=args.batch_size)`. (Do NOT modify `OllamaEmbeddingClient.__init__`.)
- [x] 9.4 Instantiate `OllamaEmbeddingClient(settings)` (the constructor is `(settings, transport=None, clock=None)`; no `batch_size` argument). Instantiate the index repository, the indexer, and the seeder.
- [x] 9.5 Call `seeder.run(session, id_comercio=..., id_producto=..., id_producto_presentacion=..., force=args.force, dry_run=args.dry_run)`. Record start time.
- [x] 9.6 Print one line per presentation: `id_producto_presentacion=<id> status=<status> reason=<reason>` (omit reason when `None`).
- [x] 9.7 Print summary `model=<embedding_model> dim=<embedding_dimension> created=<n> updated=<n> unchanged=<n> stale=<n> inactive=<n> failed=<n> elapsed=<seconds>s`.
- [x] 9.8 Exit `0` when `--dry-run` is set, when `failed==0` in a real run, or when the run completes without unhandled exception; exit `1` when `failed>0` in a real run (recoverable embedding failures persist the `failed` rows, commit once, exit `1`) or when an unhandled exception escapes. A `--dry-run` exits `0` regardless of the `failed` counter (the dry-run is read-only and never commits).
- [x] 9.9 Wrap the call in `try/except/finally`: `session.commit()` once at the end of the `try` block on success; `session.rollback()` once in the `except` block on any unhandled exception; `session.close()` in `finally`. The structure mirrors `backend/scripts/seed_product_aliases.py`. A `--dry-run` follows the same `try/except/finally` shape but the `try` block does NOT call `session.commit()`; the session is closed in `finally` without a prior commit.

## 10. Migration integrity tests

- [x] 10.1 Create `backend/tests/test_producto_presentacion_embedding_migration.py` against `supernova_test`.
- [x] 10.2 Cover the schema after `alembic upgrade head`: assert the table exposes the new columns, the legacy unique constraint is gone, the two partial unique indexes exist (`pg_indexes` lookup), all seven `CHECK` constraints exist (including `embedding_status_chk`), and `vector` is nullable.
- [x] 10.3 Cover document-level uniqueness: insert two rows with the same `(id_producto_presentacion, modelo, source_type='canonical', source_record_id=None)` and assert the second insert raises `IntegrityError`; insert two alias rows with the same `(id_producto_presentacion, modelo, source_type='alias', source_record_id=17)` and assert the same.
- [x] 10.4 Cover non-null `source_record_id` coexistence: insert one canonical row (`source_record_id=None`) and one alias row (`source_record_id=17`) for the same presentation and assert both persist (the partial indexes are disjoint).
- [x] 10.5 Cover vector nullability: insert a `failed` row with `vector=NULL` and assert it persists. Insert a `ready` row with `vector=NULL` and assert the `ready_vector_chk` rejects it.
- [x] 10.6 Cover `source_type_chk`: insert with `source_type='unknown'` and assert rejection.
- [x] 10.7 Cover `source_record_id_alias_chk`: insert `alias` with `source_record_id=None` (rejected) and `canonical` with `source_record_id=5` (rejected).
- [x] 10.8 Cover `content_hash_chk`: insert with uppercase / wrong-length / non-hex characters and assert rejection.
- [x] 10.9 Cover `source_text_nonempty_chk` and `normalized_text_nonempty_chk`: insert with whitespace-only text and assert rejection.
- [x] 10.10 Cover `embedding_status_chk`: insert with `embedding_status='unknown'` and assert the database rejects it.

## 11. Indexer tests (minimum indispensable)

- [x] 11.1 Create `backend/tests/test_producto_presentacion_embedding_indexer.py` against `supernova_test` using a fake `EmbeddingClientProtocol` (no real Ollama call).
- [x] 11.2 Cover **initial indexing**: an empty `producto_presentacion_embeddings` table for one presentation produces `created` rows for every document the builder emits; the embedding client is called once per batch; the six counters aggregate correctly.
- [x] 11.3 Cover **hash-based idempotency**: re-run the indexer against the same catalog with no catalog change → every document is `unchanged`, the embedding client is NOT called.
- [x] 11.4 Cover **semantic updates**: change the product name (`Pizza de Muzzarella` → `Pizza de Jamón y Queso`) and re-run → the `canonical` and `combined` rows are `updated`, the alias rows are `unchanged`. Source-text differences producing the same normalized text are treated as `unchanged` (no Ollama call).
- [x] 11.5 Cover **alias stale behavior**: delete an alias and re-run → the row for the deleted alias transitions to `stale`, the previous vector is preserved.
- [x] 11.6 Cover **inactive catalog behavior**: deactivate a `Producto` and re-run → every row for that product's presentations transitions to `inactive`, the pure builder is NOT run, the embedding client is NOT called.
- [x] 11.7 Cover **batch failure semantics**: a fake `EmbeddingClientProtocol` that raises `EmbeddingConnectionError` for one batch → every document in that batch transitions to `failed` with `last_error`, the previous vector is preserved when a row already existed, and the indexer continues with the next presentation's batch.
- [x] 11.8 Cover **commerce isolation**: run with `id_comercio=1` and assert only the presentations of comercio 1 are loaded; inactive presentations of comercio 1 are NOT silently dropped.
- [x] 11.9 Cover **state machine reactivation paths**: a `stale` row transitions to `ready` when the builder starts producing the document again; an `inactive` row transitions to `ready` when the catalog chain becomes active again; a `failed` row transitions to `ready` on a successful re-run.
- [x] 11.10 Cover **batch size binding**: when a presentation has more applicable documents than `Settings.embedding_batch_size`, the indexer splits them into sequential bounded batches.
- [x] 11.11 Cover **`--force` updates an unchanged ready document**: with a presentation whose every ready document matches the stored `content_hash` and `embedding_status='ready'`, `activo=True`, present dimension-valid `vector`, running the indexer with `force=True` returns `updated` for every applicable document, the embedding client IS called, and the row's `vector`, `source_text`, `normalized_text`, `content_hash` are rewritten, `embedding_status='ready'`, `activo=True`, `last_error=NULL`, `fecha_ultima_modificacion` advanced.
- [x] 11.12 Cover **failed/stale/inactive rows return to ready after successful regeneration**: for a presentation with one row in each of `failed`, `stale`, `inactive`, running the indexer against an active catalog chain returns `updated` for each, and the resulting rows have `embedding_status='ready'`, `activo=True`, `last_error=NULL`, `vector` rewritten, `fecha_ultima_modificacion` advanced.
- [x] 11.13 Cover **a new failed document creates a failed row**: a fake `EmbeddingClientProtocol` that raises `EmbeddingClientError` for a batch whose documents have no existing rows; after the run, every document has a row with `embedding_status='failed'`, `vector=NULL`, `activo=True`, sanitized `last_error`, and the `failed` counter equals the batch size.
- [x] 11.14 Cover **an existing failed batch preserves the previous vector**: a fake `EmbeddingClientProtocol` that raises `EmbeddingClientError` for a batch whose documents already have rows in `ready` with stored vectors; after the run, every document has a row with `embedding_status='failed'`, `last_error=<safe message>`, the previous `vector` preserved, `activo=True`, and `fecha_alta` preserved.
- [x] 11.15 Cover **an update persists `source_text` and `normalized_text`**: after `service.create_or_update_document(...)` returns `updated`, the row's `source_text` and `normalized_text` columns equal the incoming document's values (asserted by direct column read).
- [x] 11.16 Cover **dry-run is strictly read-only**: with `dry_run=True`, assert `embed_documents` is NOT called, `repository.insert_document` / `update_document` / `mark_status` are NOT called, `session.flush()` is NOT called, `service.mark_stale` / `mark_inactive` are NOT called, `session.commit()` is NOT called; planned `created` / `updated` / `unchanged` / `stale` / `inactive` totals are reported in the result; no row in `producto_presentacion_embeddings` is inserted or updated.

## 12. CLI runner tests

- [x] 12.1 Create `backend/tests/test_seed_product_presentation_embeddings_cli.py` (subprocess-based) against `supernova_test`.
- [x] 12.2 Cover **dry-run behavior**: run with `--dry-run`, assert the embedding client is NOT called (assert via call-counter on the fake injected through the same module surface), no rows are inserted, no `commit()` is called, no `flush()` is called, `mark_stale` / `mark_inactive` are NOT called, and the summary line still prints the six required counters.
- [x] 12.3 Cover **dry-run failed scope**: assert `dry_run.failed` counts ONLY data-side failures (catalog projection errors, `InvalidProductEmbeddingDocument`, stored-vector dimension mismatch); it CANNOT include Ollama failures.
- [x] 12.4 Cover **flag validation**: `--help` lists the six flags; `--batch-size 0` or negative `--batch-size` is rejected by argparse before any construction happens.
- [x] 12.5 Cover **batch-size override**: assert that `--batch-size 16` calls `dataclasses.replace(settings, embedding_batch_size=16)` and passes the resulting frozen `Settings` to `OllamaEmbeddingClient`. Assert the persisted `Settings` is unchanged.
- [x] 12.6 Cover **report fields**: a real run prints `model=`, `dim=`, `created=`, `updated=`, `unchanged=`, `stale=`, `inactive=`, `failed=`, `elapsed=`.

## 13. Regression coverage (minimum indispensable)

- [x] 13.1 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_embedding_document_builder.py -q` to confirm Subphase 4.5 builder / normalization still passes.
- [x] 13.2 Run `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_ollama_embedding_client.py -q` to confirm Subphase 4.4 embedding client still passes.
- [x] 13.3 Run the directly affected Subphase 4.3 persistence tests (the legacy `ProductoPresentacionEmbeddingService` and `ProductoPresentacionEmbeddingRepository` deprecated wrappers must still pass against `supernova_test`).
- [x] 13.4 Do NOT require the full `api_smoke.py` run or unrelated fuzzy-recognizer suites unless a focused test reveals a regression there.

## 14. Static checks

- [x] 14.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0.
- [x] 14.2 `PYTHONPATH=. venv/bin/python -m ruff check backend/models/producto_presentacion_embedding.py backend/repositories/producto_presentacion_embedding_repository.py backend/repositories/producto_presentacion_embedding_index_repository.py backend/services/producto_presentacion_embedding_service.py backend/services/producto_presentacion_embedding_indexer.py backend/services/producto_presentacion_embedding_seeder.py backend/scripts/seed_product_presentation_embeddings.py backend/alembic/versions/ backend/tests/test_producto_presentacion_embedding_migration.py backend/tests/test_producto_presentacion_embedding_indexer.py backend/tests/test_seed_product_presentation_embeddings_cli.py` reports no new failures.
- [x] 14.3 `PYTHONPATH=. venv/bin/python -m mypy backend/models/producto_presentacion_embedding.py backend/repositories/producto_presentacion_embedding_repository.py backend/repositories/producto_presentacion_embedding_index_repository.py backend/services/producto_presentacion_embedding_service.py backend/services/producto_presentacion_embedding_indexer.py backend/services/producto_presentacion_embedding_seeder.py backend/scripts/seed_product_presentation_embeddings.py` reports no new errors.
- [x] 14.4 Verify the indexer / seeder modules contain no `commit` / `rollback` / `close` / `begin` calls: `grep -nE "session\.(commit|rollback|close|begin)\(" backend/services/producto_presentacion_embedding_indexer.py backend/services/producto_presentacion_embedding_seeder.py backend/repositories/producto_presentacion_embedding_repository.py backend/services/producto_presentacion_embedding_service.py backend/repositories/producto_presentacion_embedding_index_repository.py` returns no matches.
- [x] 14.5 `openspec validate seed-product-presentation-embeddings-4-6 --strict` is valid; the change remains active and unsynchronized.

## 15. Manual verification

- [x] 15.1 `PYTHONPATH=. venv/bin/alembic upgrade head` against `supernova_test` and against `supernova`; confirm `alembic current` reports the new revision; confirm `\d producto_presentacion_embeddings` lists the new columns, the seven `CHECK` constraints (including `embedding_status_chk`), and the two partial unique indexes.
- [x] 15.2 `PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_presentation_embeddings --dry-run` against `supernova`; confirm the summary prints the six required counters and the exit code is `0`.
- [x] 15.3 `PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_presentation_embeddings` against `supernova`; confirm `created=N updated=0 unchanged=0 stale=0 inactive=0 failed=0` for a fresh database; record the elapsed time.
- [x] 15.4 Re-run without flags; confirm `created=0 updated=0 unchanged=N stale=0 inactive=0 failed=0` (idempotent re-run reports `unchanged`).
- [x] 15.5 `PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_presentation_embeddings --force`; confirm every applicable document is regenerated and the `updated` counter equals the document count for the active presentations.
- [x] 15.6 `PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_presentation_embeddings --batch-size 8`; confirm the CLI runs without error and the per-presentation outcomes are recorded (no `OllamaEmbeddingClient.__init__` modification is required).
- [x] 15.7 Spot-check the rows: `psql supernova -c "SELECT id_producto_presentacion, source_type, source_record_id, embedding_status, activo FROM producto_presentacion_embeddings ORDER BY id_producto_presentacion, source_type, source_record_id LIMIT 20;"` — confirm one row per `(id_producto_presentacion, source_type, source_record_id)` for the active presentations and that `embedding_status='ready'`.

## 16. Reporting

- [x] 16.1 Report the migration revision, the new columns, the seven table-level `CHECK` constraints (including `embedding_status_chk`), the two partial unique indexes, the `EmbeddingStatus(str, enum.Enum)` representation, the authoritative reactivation-friendly state machine, the per-document repository / service refactor (`update_document(...)` persists the complete document metadata; `record_failed_document(...)` handles embedding failures; legacy aggregate wrappers preserved as deprecated), the new indexer and seeder modules (with explicit no-commit / no-rollback / no-close / no-begin verification), the inactive-first detection rule, the precise batching semantics, the CLI flags and report fields, the `--batch-size` implementation through `dataclasses.replace` (without modifying the embedding client constructor), the strict `--dry-run` behavior (no writes, no `flush()`, no Ollama, no commit), the CLI transaction behavior (recoverable failures persist and commit once with exit `1`; unhandled errors roll back; dry-run never commits), the deterministic `downgrade()` (truncate before restoring the legacy uniqueness rule and `vector NOT NULL`), files changed, tests executed and their results, and confirm that no model / FastAPI / settings / recognizer / embedding-client / pure-builder module was changed in behavior, the embedding client is untouched, the pure builder is untouched, and the OpenSpec change remains active.