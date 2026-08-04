## Why

The hybrid recognizer roadmap (Phase 4) has produced the durable persistence boundary for embeddings (Subphase 4.3) and a provider-neutral Ollama client (Subphase 4.4), but it is still missing the deterministic transformation that turns a `producto_presentacion` and its persisted aliases into the text that will actually be embedded. Without a stable, content-addressed document builder there is no way to decide whether a persisted embedding is still valid after a catalog change, no reproducible input for similarity search evaluation, and no shared artifact that future semantic, hybrid, and reindexing subphases can rely on.

This subphase introduces that pure component so subsequent subphases can focus on indexing, vector search, and hybrid wiring without re-deriving the document shape each time.

## What Changes

- Add a new pure component `ProductEmbeddingDocumentBuilder` in `backend/embeddings/product_embedding_document_builder.py` that transforms a caller-supplied catalog projection into a deterministic list of `ProductEmbeddingDocument` records.
- Define explicit input projections: `ProductEmbeddingCatalogProjection` for the per-presentation catalog data, and `ProductEmbeddingAliasInput` for each applicable alias (with `id_producto_presentacion` populated for presentation-specific aliases and `None` for product-wide aliases).
- Define a stable output contract `ProductEmbeddingDocument` with `producto_id`, `producto_presentacion_id`, `source_type` (`canonical` | `description` | `alias` | `combined`), `source_record_id`, `source_text`, `normalized_text`, and `content_hash`.
- Generate four document types per presentation: `canonical` (product + presentation), `description` (only when product description is non-empty), `alias` (one per active applicable alias, scope-aware), and `combined` (deterministic category/product/description/presentation record).
- Reuse and project the existing recognizer's normalization function (lowercase + Unicode NFD + ASCII fallback + whitespace collapse) without changing it, so the same canonical text gets the same hash across the recognizer, this builder, and any future consumer.
- Compute a deterministic SHA-256 `content_hash` over `producto_presentacion_id`, `source_type`, `source_record_id` (when present), and `normalized_text`; same input always yields the same hash, semantic changes alter the affected hash.
- Enforce strict validation (missing product id, missing presentation id, empty product name, both presentation code and description empty, presentation-specific alias pointing at another presentation, invalid alias scope) by raising typed `InvalidProductEmbeddingDocument` exceptions.
- Deduplicate alias documents by `normalized_text`, ignore inactive aliases, ignore presentation-specific aliases whose `id_producto_presentacion` does not match the target presentation, and never generate alias documents from structured presentation data (`chica`, `grande`, `unidad`, `1 litro`).
- Add focused tests covering canonical, description, combined, alias scope, presentation distinction, deterministic hashing, duplicate removal, ordering stability, inactive-alias exclusion, Unicode normalization, and invalid-ownership rejection.
- No embeddings are generated, no `producto_presentacion_embeddings` rows are written, no Ollama call is made, and the existing fuzzy recognizer is not modified.

## Capabilities

### New Capabilities

- `product-embedding-documents`: pure component that builds deterministic semantic documents and content hashes for `producto_presentacion` catalog data using persisted product and product-presentation aliases.

### Modified Capabilities

None. Subphases 4.1 (`product-recognizer-contract`, `product-recognizer-baseline-dataset`), 4.2 (`product-alias-persistence`), 4.3 (`producto-presentacion-embeddings`), and 4.4 (`ollama-embedding-client`) are unchanged — this subphase adds a new capability, it does not modify their requirements.

## Impact

- New module: `backend/embeddings/product_embedding_document_builder.py` (pure, infrastructure-free, no SQLAlchemy / HTTP / Ollama / pgvector / repository imports).
- New tests: `backend/tests/test_product_embedding_document_builder.py` (focused unit tests, no database or LLM access).
- No model, migration, repository, service, router, recognizer, persistence, or configuration change.
- No embeddings are generated and no `producto_presentacion_embeddings` rows are written by this subphase.
- The OpenSpec change remains active after apply; sync and archive are explicit user commands.
