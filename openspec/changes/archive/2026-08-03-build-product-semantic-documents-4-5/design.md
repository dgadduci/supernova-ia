## Context

Phase 4 is preparing the hybrid recognizer stack. Subphase 4.1 froze the product recognizer contract and seeded the baseline dataset. Subphase 4.2 moved product and product-presentation aliases into PostgreSQL (`producto_aliases`) behind a service boundary. Subphase 4.3 enabled the `pgvector` extension and created the durable `producto_presentacion_embeddings` table plus a `ProductoPresentacionEmbeddingService`. Subphase 4.4 added a local Ollama embedding client behind an `EmbeddingClientProtocol` with independent `EMBEDDING_*` settings.

The pipeline still lacks the deterministic transformation that turns a `producto_presentacion` and its applicable aliases into the text that will be embedded. The recognizer owns one form of canonical text (`_normalizar_texto`), but there is no shared, content-addressed document shape that a future indexing subphase can compare against stored embeddings, that a reindexing subphase can use to detect drift, and that semantic-search evaluation can use as a reproducible input.

The change must remain pure: no database access from the builder, no embedding generation, no Ollama call, no migration, no router, no model change. The output is the canonical input to whatever calls the embedding client next.

## Goals / Non-Goals

**Goals:**
- Introduce a pure, infrastructure-free `ProductEmbeddingDocumentBuilder` that converts a caller-supplied `ProductEmbeddingCatalogProjection` plus applicable `ProductEmbeddingAliasInput` records into a deterministic list of `ProductEmbeddingDocument` records.
- Reuse the existing recognizer-style normalization (lowercase + NFD + ASCII fallback + whitespace collapse, preserving `ñ`) so the same canonical text maps to the same hash across the recognizer, the builder, and any future consumer.
- Produce four document types — `canonical`, `description` (optional), `alias` (one per applicable active alias, scope-aware), and `combined` — with stable ordering, deterministic SHA-256 hashes, and a 64-character lowercase hex digest.
- Enforce strict validation (missing product/presentation id, empty product name, missing presentation, invalid alias scope, presentation-specific alias pointing elsewhere) by raising typed `InvalidProductEmbeddingDocument` exceptions and producing zero documents on failure.
- Keep the builder reusable for both initial indexing and future reindexing/diff subphases without re-deriving the document shape each time.

**Non-Goals:**
- Generate embeddings (the `OllamaEmbeddingClient` from Subphase 4.4 is not invoked here).
- Persist anything in `producto_presentacion_embeddings` (Subphase 4.3 service is not called here).
- Query PostgreSQL (the builder receives the catalog projection and the alias list as plain Python objects).
- Modify the fuzzy recognizer, the recognizer contract, the alias service, the embedding service, or the Ollama client.
- Add an administrative reindex endpoint or a vector similarity search.
- Mark embeddings stale after catalog changes (a later subphase).
- Implement the hybrid recognizer (a later subphase).

## Decisions

### Decision: Pure module under `backend/embeddings/`
The builder lives in a new `backend/embeddings/` package next to the future Ollama / indexing / similarity subphases. It is a `dataclass` / `TypedDict` / `Pydantic`-style DTO module with no infrastructure imports.

**Alternatives considered:**
- *Place inside `backend/recognizers/`* — rejected; the recognizer owns a different concern (text → recognized product) and the document builder is consumed by future indexing/embedding subphases, not by the recognizer.
- *Place inside `backend/services/`* — rejected; the builder is pure, has no session, no SQLAlchemy, and no business rules over a database, so it does not match the project's "Router → Service → Repository → Model" layering for backend services.

### Decision: `dataclass(frozen=True)` for input and output DTOs
The project mixes Pydantic (request/response schemas) and `dataclass` (internal value objects, e.g. `Settings`, the embedding `ProductoPresentacionEmbedding` row). The builder is infrastructure-free and not exposed via HTTP, so `dataclass(frozen=True)` is the lightest correct fit. `TypedDict` was considered but loses explicit type enforcement at the builder boundary; `Pydantic` was considered but adds runtime validation we do not need here (we do our own typed validation).

### Decision: Reuse the recognizer's normalization without copying it
The recognizer's `_normalizar_texto` lives inside `backend/recognizers/product_recognizer.py`. The builder cannot import from the recognizer (Subphase 4.1 keeps the recognizer side-effectful and the contract module infrastructure-free, and pulling in the recognizer would couple the builder to fuzzy side effects).

The new module `backend/embeddings/text_normalization.py` hosts a small `normalize_for_embedding(text: str) -> str` function that follows the exact same algorithm (lowercase, NFD, drop combining diacritics via `unicodedata.combining`, drop everything outside `[a-z0-9ñ\s]`, collapse whitespace, strip) and is asserted to be byte-identical to the recognizer's `_normalizar_texto` in a focused unit test. A future subphase can refactor both to share a single module without changing observable behavior.

**Alternatives considered:**
- *Import `_normalizar_texto` from the recognizer* — rejected; the recognizer is a side-effect-prone module and the contract calls for infrastructure-free recognizer consumers.
- *Introduce a new normalization policy* — rejected; the spec says "consistent with the project's established text-normalization policy" and changing it now would break recognizer round-trips.

### Decision: `source_text` vs `normalized_text`
`source_text` keeps the original accents and casing for readability and customer-facing presentation; `normalized_text` is the embedding input. This split lets a future reindexing subphase show the operator the readable text while still hashing on the embedding input.

### Decision: SHA-256 over `(id, source_type, source_record_id, normalized_text)`
The hash uses the deterministic concatenation `f"{id_producto_presentacion}\x1f{source_type}\x1f{source_record_id or ''}\x1f{normalized_text}"` with the ASCII unit-separator `\x1f` as the field delimiter, then `hashlib.sha256(...).hexdigest()`. The unit-separator guarantees that `canonical` + `""` cannot collide with `canon` + `ical`, etc. The spec forbids including timestamps, session data, process ids, random values, or memory representations.

**Alternatives considered:**
- *BLAKE2* — considered, but SHA-256 is the project standard for content hashing and matches the user's spec.
- *Pickle / object id* — rejected; would couple the hash to runtime identity and break determinism.

### Decision: Alias scope carried explicitly in the input
The Subphase 4.2 alias service already separates `id_producto_presentacion IS NULL` (product-wide) from a non-null value (presentation-specific). The builder accepts both shapes through a single `ProductEmbeddingAliasInput` with a `scope` literal and an `id_producto_presentacion` field that is required for `product_presentacion` and must be `None` for `product`. This is more explicit than passing raw ORM dicts and keeps the builder infrastructure-free.

### Decision: Validation raises `InvalidProductEmbeddingDocument(ValueError)`
The builder raises a typed `ValueError` subclass so callers can catch it specifically. Returning zero documents on failure is enforced by raising before any list construction.

**Alternatives considered:**
- *Return an empty list* — rejected; the spec mandates "The builder must not silently generate incomplete documents" and an empty list would mask the validation failure.
- *Project-local exception class with its own base* — rejected; `ValueError` is the standard Python "input was wrong" signal and matches the `pydantic.ValidationError` / `ValueError` pattern used elsewhere in the project.

## Risks / Trade-offs

- **[Risk] Two normalization functions can drift over time** → Mitigation: focused test asserts byte-identical output of `normalize_for_embedding` and the recognizer's `_normalizar_texto` for a representative corpus (lowercase, accented, whitespace, digits, `ñ`, punctuation); a future refactor subphase can move both to a shared module.
- **[Risk] A future schema change introduces new fields the builder ignores silently** → Mitigation: the explicit input projection declares the schema; an unexpected field is ignored but the test suite asserts that every known field is consumed; adding a new field requires an explicit input-projection update.
- **[Risk] A new `source_type` could be added without a contract update** → Mitigation: the literal `Literal[...]` type for `source_type` is part of the public surface; adding a value is a contract change that lands in a new subphase with its own spec.
- **[Risk] SHA-256 hex encoding differences (uppercase, prefixes) break equality** → Mitigation: the test asserts `len == 64` and `all(c in "0123456789abcdef" for c in digest)`, and a second deterministic build returns the same string.

## Migration Plan

No migration. This subphase introduces a new pure module and its tests; no database, model, configuration, or production code path is touched. The OpenSpec change remains active after `/opsx:apply`; sync and archive are explicit user commands per the project's workflow rule.

## Open Questions

None. The builder is fully specified by the proposal, the spec, and the existing recognizer / alias / embedding persistence / embedding client subphases.
