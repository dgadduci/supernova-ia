# Capability: product-embedding-documents

## Purpose

TBD

## Requirements

### Requirement: Deterministic product-presentation semantic documents

The system SHALL provide a pure `ProductEmbeddingDocumentBuilder` component that transforms a caller-supplied catalog projection for one `producto_presentacion` into a deterministic list of `ProductEmbeddingDocument` records. The builder SHALL NOT import SQLAlchemy, repositories, HTTP, Ollama, pgvector, or product recognizers and SHALL perform no network, database, file system, or embedding operation.

#### Scenario: Builder exists in the embeddings package

- **WHEN** the project source tree is inspected
- **THEN** `backend/embeddings/product_embedding_document_builder.py` exports `ProductEmbeddingDocumentBuilder` and the supporting DTOs through `__all__`
- **AND** the module imports nothing from `sqlalchemy`, `backend.repositories`, `backend.recognizers`, `backend.llm`, `backend.models`, `requests`, `fastapi`, `pgvector`, or any HTTP/Ollama client

#### Scenario: Pure builder is constructable without infrastructure

- **WHEN** `ProductEmbeddingDocumentBuilder()` is instantiated in a unit test
- **THEN** the constructor performs no I/O and the instance is reusable for any number of builds

### Requirement: Builder input projection

The builder SHALL accept a single `ProductEmbeddingCatalogProjection` argument describing the target `producto_presentacion` and an iterable of `ProductEmbeddingAliasInput` records describing the persisted aliases already filtered to be applicable. The projection SHALL include `producto_id`, `producto_presentacion_id`, `producto_nombre`, `producto_descripcion` (nullable), `categoria_nombre`, `presentacion_id`, `presentacion_codigo` (nullable), and `presentacion_descripcion` (nullable). Each alias input SHALL include `id` (the alias row id), `alias` (raw text), `alias_normalizado`, `scope` (`"product"` or `"product_presentacion"`), `activo`, and `id_producto_presentacion` (required for the `product_presentacion` scope, must be `None` for the `product` scope).

#### Scenario: Required catalog fields are present

- **WHEN** a caller supplies a `ProductEmbeddingCatalogProjection`
- **THEN** the builder accepts it and uses `producto_id`, `producto_presentacion_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, and `presentacion_descripcion` to compose every document
- **AND** the projection does not require a `Producto` or `ProductoPresentacion` ORM instance

#### Scenario: Alias input carries scope and ownership

- **WHEN** a caller supplies a `ProductEmbeddingAliasInput`
- **THEN** the builder reads `alias`, `alias_normalizado`, `scope`, `activo`, `id_producto_presentacion`, and `id` and uses them to decide inclusion, ordering, and `source_record_id`

### Requirement: Output document contract

The builder SHALL return a list of `ProductEmbeddingDocument` records. Each document SHALL contain `producto_id: int`, `producto_presentacion_id: int`, `source_type: "canonical" | "description" | "alias" | "combined"`, `source_record_id: int | None` (the alias id for `alias` documents, otherwise `None`), `source_text: str` (the readable, accent-preserving text), `normalized_text: str` (the deterministic normalization), and `content_hash: str` (a 64-character lowercase hex SHA-256 digest).

#### Scenario: Document exposes all required fields

- **WHEN** the builder returns documents for any valid projection
- **THEN** every document has `producto_id`, `producto_presentacion_id`, `source_type`, `source_record_id` (or `None`), `source_text`, `normalized_text`, and `content_hash` populated
- **AND** the `content_hash` is exactly 64 lowercase hex characters

#### Scenario: source_text preserves accents while normalized_text strips them

- **WHEN** a product name like `Pizza de Muzzarella` is processed
- **THEN** the document's `source_text` reads `Pizza de Muzzarella` (accents preserved)
- **AND** the `normalized_text` reads `pizza de muzzarella` (no accents, single spaces, lowercase)

### Requirement: Canonical document

The builder SHALL emit exactly one `canonical` document per presentation whose `source_text` is the product name followed by a single space and the structured presentation data (`presentacion_descripcion` when present, otherwise `presentacion_codigo`).

#### Scenario: Canonical document with description

- **WHEN** the projection has `producto_nombre="Pizza de Muzzarella"` and `presentacion_descripcion="Grande"`
- **THEN** the canonical document's `source_text` is exactly `Pizza de Muzzarella Grande`
- **AND** its `source_type` is `canonical` and `source_record_id` is `None`

#### Scenario: Canonical document falls back to code

- **WHEN** the projection has `producto_nombre="Coca"` and `presentacion_descripcion=""` and `presentacion_codigo="1L"`
- **THEN** the canonical document's `source_text` is exactly `Coca 1L`

### Requirement: Description document

The builder SHALL emit exactly one `description` document when `producto_descripcion` is a non-empty string after trimming. The document's `source_text` SHALL be the canonical text followed by a period, a space, and the description text. The document SHALL be omitted entirely when the description is missing, `None`, or empty after trimming.

#### Scenario: Description document generated when description exists

- **WHEN** the projection has `producto_nombre="Pizza de Muzzarella"`, `presentacion_descripcion="Grande"`, and `producto_descripcion="Pizza con salsa de tomate y queso mozzarella"`
- **THEN** the description document's `source_text` is exactly `Pizza de Muzzarella Grande. Pizza con salsa de tomate y queso mozzarella.`

#### Scenario: Description document omitted when description is empty

- **WHEN** the projection has `producto_descripcion=""` or `producto_descripcion=None`
- **THEN** the builder returns no `description` document and the output list still contains `canonical`, `alias` (if any), and `combined`

### Requirement: Alias documents

The builder SHALL emit one `alias` document per persisted active alias applicable to the target presentation. The document's `source_text` SHALL be the alias text followed by a single space and the structured presentation data. The document's `source_record_id` SHALL be the alias row id. A general product alias (scope `product`) SHALL be eligible for every presentation of that product. A presentation-specific alias (scope `product_presentacion`) SHALL be eligible only when its `id_producto_presentacion` equals the target `producto_presentacion_id`.

#### Scenario: Product-wide alias applies to every presentation

- **WHEN** the projection belongs to product 7, presentation 31, and the alias list contains a `product` alias with text `Muzza`
- **THEN** the output includes one alias document with `source_text="Muzza Grande"` (or with the appropriate presentation text)
- **AND** the same alias is also included when the projection switches to a different presentation of product 7 (e.g. `Chica`)

#### Scenario: Presentation-specific alias does not leak

- **WHEN** the alias list contains a `product_presentacion` alias for `producto_presentacion_id=42` with text `Coca de litro`
- **THEN** the document is emitted only when the target `producto_presentacion_id` is `42`
- **AND** it is excluded for any other presentation, including sibling presentations of the same product

#### Scenario: Inactive aliases are excluded

- **WHEN** the alias list contains an alias with `activo=False`
- **THEN** no alias document is generated for it
- **AND** it does not appear in any other source_type

#### Scenario: Alias documents are not generated from presentation codes

- **WHEN** the projection's `presentacion_codigo` is `unidad` and no alias with text `unidad` is supplied
- **THEN** the output does not contain an alias document with text `unidad`; the structured presentation data appears only inside `canonical`, `description`, and `combined` documents

### Requirement: Combined document

The builder SHALL emit exactly one `combined` document whose `source_text` concatenates `Categoría: <categoria_nombre>. Producto: <producto_nombre>. Descripción: <producto_descripcion or empty>. Presentación: <structured presentation text>.`. The `Descripción:` segment SHALL be omitted entirely when the description is missing, `None`, or empty after trimming (no `None`, no `''` placeholder, no double space).

#### Scenario: Combined document includes every segment

- **WHEN** the projection has `categoria_nombre="Pizzas"`, `producto_nombre="Pizza de Muzzarella"`, `producto_descripcion="Pizza con salsa de tomate y queso mozzarella"`, and `presentacion_descripcion="Grande"`
- **THEN** the combined document's `source_text` is exactly `Categoría: Pizzas. Producto: Pizza de Muzzarella. Descripción: Pizza con salsa de tomate y queso mozzarella. Presentación: Grande.`

#### Scenario: Combined document omits description cleanly

- **WHEN** the projection has `producto_descripcion=""`
- **THEN** the combined document's `source_text` contains `Categoría: ... Producto: ... Presentación: ...` and does not contain a `Descripción:` segment or any trailing ` None`

### Requirement: Presentation handling

The builder SHALL treat presentation data as mandatory. It SHALL choose `presentacion_descripcion` when non-empty (after trimming), otherwise `presentacion_codigo`. Two presentations of the same product SHALL produce different `canonical` and `combined` documents whenever the structured presentation text differs (e.g. `Chica` vs `Grande`, `Unidad` vs `1 Litro`).

#### Scenario: Different presentations of the same product differ

- **WHEN** the builder is called twice for two projections of the same product whose `presentacion_descripcion` values are `Chica` and `Grande`
- **THEN** the resulting `canonical` and `combined` `source_text` strings are different
- **AND** the corresponding `content_hash` values are different

#### Scenario: Presentation text is required

- **WHEN** a projection has both `presentacion_codigo=""` and `presentacion_descripcion=""`
- **THEN** the builder raises `InvalidProductEmbeddingDocument` and returns no documents

### Requirement: Text normalization

The builder SHALL apply a single deterministic normalization function for every `normalized_text`. The function SHALL trim leading and trailing whitespace, collapse repeated internal whitespace, lowercase the result, decompose Unicode using NFD, drop combining diacritics, and keep alphanumeric characters, internal single spaces, and the `ñ` character. The `source_text` SHALL preserve the original accents and casing.

#### Scenario: Normalization is deterministic and accent-stripping

- **WHEN** the builder processes `Pizza  de   Muzzárella`
- **THEN** the document's `normalized_text` is exactly `pizza de muzzarella`
- **AND** the document's `source_text` preserves `Muzzárella`

#### Scenario: Normalization deduplicates equivalent inputs

- **WHEN** the builder is called twice with source text `  Muzzá   ` and `muzza`
- **THEN** both inputs produce the same `normalized_text` (`muzza`)
- **AND** documents with the same `(producto_presentacion_id, source_type, source_record_id, normalized_text)` have the same `content_hash`

### Requirement: Content hash

The builder SHALL compute `content_hash` as the lowercase hexadecimal SHA-256 digest of the concatenation of `producto_presentacion_id`, a fixed separator, `source_type`, a fixed separator, `source_record_id` (the literal string `""` when `None`), a fixed separator, and `normalized_text`. The hash input SHALL NOT include timestamps, session data, process ids, random values, or object memory representations. Any semantic change to product name, description, category, presentation, or alias text SHALL change the relevant hash.

#### Scenario: Hash inputs are explicit and minimal

- **WHEN** a document is built for `producto_presentacion_id=31`, `source_type="canonical"`, `source_record_id=None`, and `normalized_text="pizza de muzzarella grande"`
- **THEN** the hash input bytes are exactly `b"31\x1fcanonical\x1f\x1fpizza de muzzarella grande"`
- **AND** the resulting `content_hash` is the lowercase hex digest of that byte string

#### Scenario: Semantic change alters the relevant hash

- **WHEN** two builds differ only in `producto_nombre` (`Pizza de Muzzarella` vs `Pizza de Jamón y Queso`)
- **THEN** their `canonical`, `description`, and `combined` hashes all differ
- **AND** their `combined` `source_text` and `normalized_text` differ

#### Scenario: Alias change alters only the alias hash

- **WHEN** an alias text changes from `Muzza` to `Mozza`
- **THEN** the alias document's `content_hash` changes
- **AND** the `canonical`, `description`, and `combined` hashes are unchanged

### Requirement: Duplicate handling and ordering

The builder SHALL deduplicate alias documents whose `normalized_text` is equal, SHALL keep the document with the lowest `source_record_id` (alias id) when duplicates are found, and SHALL never drop a non-alias document in favor of an alias document. The output list SHALL always be ordered as `canonical`, `description` (when present), `alias` documents in stable order, then `combined`. Alias documents SHALL be ordered first by `normalized_text` ascending, then by `source_record_id` ascending.

#### Scenario: Duplicate normalized aliases collapse

- **WHEN** the alias list contains two active aliases with the same `alias_normalizado` and different `id` values
- **THEN** the output contains exactly one alias document for that normalized text
- **AND** the surviving document's `source_record_id` is the lower alias id

#### Scenario: Output order is stable

- **WHEN** the builder is called twice with the same projection and alias list
- **THEN** both calls return documents in the same order: `canonical`, `description` (if any), `alias` documents in `(normalized_text, source_record_id)` ascending order, then `combined`

### Requirement: Validation and error handling

The builder SHALL raise `InvalidProductEmbeddingDocument` (a typed `ValueError` subclass) and return no documents when any of the following is true: `producto_id` is missing or not a positive integer; `producto_presentacion_id` is missing or not a positive integer; `producto_nombre` is missing, empty, or only whitespace; both `presentacion_codigo` and `presentacion_descripcion` are missing, empty, or only whitespace; an alias has an unrecognized `scope`; or a `product_presentacion` alias has a non-`None` `id_producto_presentacion` that does not match the target `producto_presentacion_id`.

#### Scenario: Empty product name is rejected

- **WHEN** the projection has `producto_nombre="   "`
- **THEN** the builder raises `InvalidProductEmbeddingDocument("producto_nombre must not be empty")` and no documents are produced

#### Scenario: Cross-presentation alias is rejected

- **WHEN** the alias list contains a `product_presentacion` alias whose `id_producto_presentacion` differs from the target `producto_presentacion_id`
- **THEN** the builder raises `InvalidProductEmbeddingDocument` and no documents are produced

#### Scenario: Invalid alias scope is rejected

- **WHEN** an alias input has `scope="invalid_scope"`
- **THEN** the builder raises `InvalidProductEmbeddingDocument("alias scope must be 'product' or 'product_presentacion'")` and no documents are produced
