## 1. Project layout

- [x] 1.1 Create `backend/embeddings/__init__.py` exposing the package public surface.
- [x] 1.2 Create `backend/embeddings/text_normalization.py` with `normalize_for_embedding(text: str) -> str` and `__all__ = ["normalize_for_embedding"]`; no infrastructure imports.
- [x] 1.3 Create `backend/embeddings/product_embedding_document_builder.py` with the input DTOs, the output DTO, the `InvalidProductEmbeddingDocument` exception, and the `ProductEmbeddingDocumentBuilder` class; `__all__` declares the public surface.

## 2. DTO definitions

- [x] 2.1 Define `ProductEmbeddingAliasScope = Literal["product", "product_presentacion"]` (literal type) for the alias scope.
- [x] 2.2 Define `ProductEmbeddingAliasInput` as a `dataclass(frozen=True)` with `id: int`, `alias: str`, `alias_normalizado: str`, `scope: ProductEmbeddingAliasScope`, `activo: bool`, `id_producto_presentacion: int | None`.
- [x] 2.3 Define `ProductEmbeddingCatalogProjection` as a `dataclass(frozen=True)` with `producto_id: int`, `producto_presentacion_id: int`, `producto_nombre: str`, `producto_descripcion: str | None`, `categoria_nombre: str`, `presentacion_id: int`, `presentacion_codigo: str`, `presentacion_descripcion: str`.
- [x] 2.4 Define `ProductEmbeddingSourceType = Literal["canonical", "description", "alias", "combined"]` (literal type).
- [x] 2.5 Define `ProductEmbeddingDocument` as a `dataclass(frozen=True)` with `producto_id: int`, `producto_presentacion_id: int`, `source_type: ProductEmbeddingSourceType`, `source_record_id: int | None`, `source_text: str`, `normalized_text: str`, `content_hash: str`.

## 3. Text normalization

- [x] 3.1 Implement `normalize_for_embedding` with the project's established algorithm: lowercase → `unicodedata.normalize("NFD", text)` → drop combining marks → keep `[a-z0-9ñ\s]` → collapse whitespace → strip.
- [x] 3.2 Reject non-`str` input with a typed `ValueError` so the builder cannot crash on a bad caller.

## 4. Builder implementation

- [x] 4.1 Implement `ProductEmbeddingDocumentBuilder.build(projection, aliases) -> list[ProductEmbeddingDocument]`; constructor takes no arguments (or only `clock`-style dependencies — keep it parameterless).
- [x] 4.2 Validate the projection up front (positive `producto_id`, positive `producto_presentacion_id`, non-empty `producto_nombre`, non-empty presentation text); raise `InvalidProductEmbeddingDocument` on any failure.
- [x] 4.3 Validate every alias up front (recognized `scope`, presentation-specific aliases must match the target `id_producto_presentacion`); raise on the first invalid alias.
- [x] 4.4 Compute the structured presentation text (`presentacion_descripcion` if non-empty, else `presentacion_codigo`); raise when both are empty.
- [x] 4.5 Build the `canonical` document: `source_text = f"{producto_nombre} {presentacion_text}"`, `normalized_text = normalize_for_embedding(source_text)`, `source_record_id = None`.
- [x] 4.6 Build the `description` document only when `producto_descripcion` is non-empty after stripping; `source_text = f"{canonical_source_text}. {producto_descripcion}."`, `source_record_id = None`.
- [x] 4.7 Build `alias` documents: filter aliases to active + applicable scope (product-wide always applicable; presentation-specific only when `id_producto_presentacion` matches), dedupe by `alias_normalizado` keeping the lowest `id`, sort by `(alias_normalizado, id)` ascending, build `source_text = f"{alias.alias} {presentacion_text}"`, `source_record_id = alias.id`.
- [x] 4.8 Build the `combined` document: `source_text = "Categoría: {categoria_nombre}. Producto: {producto_nombre}. Descripción: {producto_descripcion or omitted}. Presentación: {presentacion_text}."` with the description segment omitted entirely when absent; `source_record_id = None`.
- [x] 4.9 Compute `content_hash` for every document as `hashlib.sha256(f"{producto_presentacion_id}\x1f{source_type}\x1f{source_record_id or ''}\x1f{normalized_text}".encode("utf-8")).hexdigest()`; the digest is exactly 64 lowercase hex characters.
- [x] 4.10 Return the documents in fixed order: `canonical`, `description` (when present), `alias` (in stable order), `combined`.
- [x] 4.11 Define `InvalidProductEmbeddingDocument(ValueError)` with a descriptive message; the builder raises it before constructing any document on validation failure.

## 5. Focused tests

- [x] 5.1 Create `backend/tests/test_product_embedding_document_builder.py` with module-level imports and a `TestProductEmbeddingDocumentBuilder` class.
- [x] 5.2 Cover canonical document with `presentacion_descripcion` and fallback to `presentacion_codigo`.
- [x] 5.3 Cover description document generation and omission when description is empty / `None` / whitespace.
- [x] 5.4 Cover combined document with and without the description segment; assert no `None` placeholder appears.
- [x] 5.5 Cover product-wide alias inclusion on every presentation and presentation-specific alias exclusion on sibling presentations.
- [x] 5.6 Cover presentation distinction: two projections of the same product with different presentations produce different `canonical` and `combined` `source_text` and different hashes; `Unidad` vs `1 Litro` distinction.
- [x] 5.7 Cover deterministic hash: identical inputs produce identical hashes; changing product name, description, category, presentation, or alias text changes the relevant hash.
- [x] 5.8 Cover duplicate removal: two aliases with the same `alias_normalizado` produce one document, with the lower `id` winning.
- [x] 5.9 Cover stable ordering: repeated calls return the same document list order; aliases sorted by `(alias_normalizado, id)`.
- [x] 5.10 Cover inactive aliases: an alias with `activo=False` does not produce a document.
- [x] 5.11 Cover Unicode and normalization: `Muzzárella` vs `muzza` produce the same `normalized_text`; `source_text` preserves the original accents; whitespace variants collapse consistently.
- [x] 5.12 Cover invalid ownership: presentation-specific alias pointing at another presentation raises `InvalidProductEmbeddingDocument`.
- [x] 5.13 Cover invalid alias scope and missing presentation text; both raise and produce zero documents.
- [x] 5.14 Add a focused byte-equality test in `test_text_normalization.py` asserting `normalize_for_embedding` produces the same output as `backend.recognizers.product_recognizer._normalizar_texto` on a representative corpus (lowercase, accented, whitespace, digits, `ñ`, punctuation).

## 6. Regression coverage

- [x] 6.1 Run `PYTHONPATH=. venv/bin/python backend/tests/test_product_recognizer_contract.py` (if present) or the Subphase 4.1 contract test surface; confirm no regression.
- [x] 6.2 Run `PYTHONPATH=. venv/bin/python backend/tests/test_producto_alias_seeder.py` (and the focused alias service / repository tests) to confirm Subphase 4.2 still passes.
- [x] 6.3 Run the Subphase 4.3 embedding persistence tests against `supernova_test` to confirm the new module does not interfere with persistence.
- [x] 6.4 Run the Subphase 4.4 Ollama client tests to confirm the embedding client is untouched and unused by the builder.

## 7. Static checks

- [x] 7.1 `PYTHONPATH=. venv/bin/python -m compileall backend` exits 0.
- [x] 7.2 `PYTHONPATH=. venv/bin/python -m ruff check backend/embeddings backend/tests/test_product_embedding_document_builder.py backend/tests/test_text_normalization.py` reports no new failures.
- [x] 7.3 `PYTHONPATH=. venv/bin/python -m mypy backend/embeddings` reports no new errors.
- [x] 7.4 `openspec validate build-product-semantic-documents-4-5 --strict` is valid; the change remains active and unsynchronized.

## 8. Reporting

- [x] 8.1 Report the builder input contract, output contract, generated source types, presentation handling, alias-scope handling, normalization strategy, hash algorithm and exact hash inputs, duplicate-handling and ordering rules, files changed, tests executed and results, and confirm no embeddings were generated, no vector records were persisted, the recognizer behavior is unchanged, and the OpenSpec change remains active.
