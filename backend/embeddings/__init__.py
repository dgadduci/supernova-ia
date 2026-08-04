"""Pure infrastructure-free embedding document builders.

This package hosts the deterministic transformation that turns a
``producto_presentacion`` and its applicable aliases into the
content-addressed documents that downstream subphases will embed, index,
and search. The package is intentionally infrastructure-free: it MUST NOT
import SQLAlchemy, repositories, HTTP, Ollama, pgvector, or product
recognizers. Any I/O wiring lives outside this package.
"""
from __future__ import annotations

from backend.embeddings.product_embedding_document_builder import (
    InvalidProductEmbeddingDocument,
    ProductEmbeddingAliasInput,
    ProductEmbeddingAliasScope,
    ProductEmbeddingCatalogProjection,
    ProductEmbeddingDocument,
    ProductEmbeddingDocumentBuilder,
    ProductEmbeddingSourceType,
)
from backend.embeddings.text_normalization import normalize_for_embedding

__all__ = [
    "InvalidProductEmbeddingDocument",
    "ProductEmbeddingAliasInput",
    "ProductEmbeddingAliasScope",
    "ProductEmbeddingCatalogProjection",
    "ProductEmbeddingDocument",
    "ProductEmbeddingDocumentBuilder",
    "ProductEmbeddingSourceType",
    "normalize_for_embedding",
]
