"""Deterministic product-presentation embedding document builder.

Subphase 4.5 introduces a pure, infrastructure-free transformation that
turns a caller-supplied ``ProductEmbeddingCatalogProjection`` plus the
applicable ``ProductEmbeddingAliasInput`` records into a deterministic
list of ``ProductEmbeddingDocument`` records. The builder is the single
source of truth for the text that downstream subphases will embed, the
content hash that determines whether a stored embedding is still valid,
and the per-source documentation that operators can show end users.

This module is intentionally infrastructure-free: it must not import
SQLAlchemy, repositories, HTTP, Ollama, pgvector, or product
recognizers. Any I/O wiring lives outside this module.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from backend.embeddings.text_normalization import normalize_for_embedding


ProductEmbeddingAliasScope = Literal["product", "product_presentacion"]
ProductEmbeddingSourceType = Literal["canonical", "description", "alias", "combined"]


_HASH_SEPARATOR: Final[str] = "\x1f"
_VALID_ALIAS_SCOPES: Final[frozenset[str]] = frozenset(
    {"product", "product_presentacion"}
)


@dataclass(frozen=True)
class ProductEmbeddingAliasInput:
    """One persisted alias already filtered to be applicable to the target.

    The builder receives its own copy of the alias data so it does not
    depend on SQLAlchemy models or repository rows. ``scope`` encodes
    whether the alias is product-wide (``"product"``) or
    presentation-specific (``"product_presentacion"``).
    """

    id: int
    alias: str
    alias_normalizado: str
    scope: ProductEmbeddingAliasScope
    activo: bool
    id_producto_presentacion: int | None


@dataclass(frozen=True)
class ProductEmbeddingCatalogProjection:
    """One ``producto_presentacion`` projected into the builder's input shape.

    The builder does not require ORM instances; every field is a plain
    Python value the caller can produce from a repository or a test.
    """

    producto_id: int
    producto_presentacion_id: int
    producto_nombre: str
    producto_descripcion: str | None
    categoria_nombre: str
    presentacion_id: int
    presentacion_codigo: str
    presentacion_descripcion: str


@dataclass(frozen=True)
class ProductEmbeddingDocument:
    """One deterministic embedding document for the target presentation."""

    producto_id: int
    producto_presentacion_id: int
    source_type: ProductEmbeddingSourceType
    source_record_id: int | None
    source_text: str
    normalized_text: str
    content_hash: str


class InvalidProductEmbeddingDocument(ValueError):
    """Raised when the projection or aliases are unsuitable for embedding.

    The builder raises this typed ``ValueError`` subclass before
    constructing any document so callers can catch the failure
    explicitly. No documents are produced on failure.
    """


class ProductEmbeddingDocumentBuilder:
    """Pure, infrastructure-free document builder for product presentations.

    The constructor takes no arguments; every dependency is supplied
    through ``build`` so the instance is reusable for any number of
    invocations without state leakage.
    """

    def __init__(self) -> None:
        return

    def build(
        self,
        projection: ProductEmbeddingCatalogProjection,
        aliases: Iterable[ProductEmbeddingAliasInput],
    ) -> list[ProductEmbeddingDocument]:
        """Return the deterministic list of documents for one presentation.

        Order is fixed: ``canonical``, ``description`` (when present),
        ``alias`` documents in stable order, then ``combined``.
        """
        aliases_tuple = self._collect_aliases(aliases)
        self._validate_projection(projection)
        self._validate_aliases(aliases_tuple, projection.producto_presentacion_id)
        presentation_text = self._resolve_presentation_text(projection)
        documents: list[ProductEmbeddingDocument] = []
        documents.append(
            self._build_canonical(projection, presentation_text)
        )
        description_doc = self._build_description(
            projection, presentation_text
        )
        if description_doc is not None:
            documents.append(description_doc)
        documents.extend(
            self._build_alias_documents(aliases_tuple, projection, presentation_text)
        )
        documents.append(
            self._build_combined(projection, presentation_text)
        )
        return documents

    @staticmethod
    def _collect_aliases(
        aliases: Iterable[ProductEmbeddingAliasInput],
    ) -> tuple[ProductEmbeddingAliasInput, ...]:
        return tuple(aliases)

    @staticmethod
    def _validate_projection(projection: ProductEmbeddingCatalogProjection) -> None:
        if not isinstance(projection.producto_id, int) or isinstance(
            projection.producto_id, bool
        ) or projection.producto_id <= 0:
            raise InvalidProductEmbeddingDocument(
                "producto_id must be a positive integer"
            )
        if (
            not isinstance(projection.producto_presentacion_id, int)
            or isinstance(projection.producto_presentacion_id, bool)
            or projection.producto_presentacion_id <= 0
        ):
            raise InvalidProductEmbeddingDocument(
                "producto_presentacion_id must be a positive integer"
            )
        if not isinstance(projection.producto_nombre, str):
            raise InvalidProductEmbeddingDocument(
                "producto_nombre must be a non-empty string"
            )
        if not projection.producto_nombre.strip():
            raise InvalidProductEmbeddingDocument(
                "producto_nombre must not be empty"
            )
        if not isinstance(projection.presentacion_codigo, str):
            raise InvalidProductEmbeddingDocument(
                "presentacion_codigo must be a string"
            )
        if not isinstance(projection.presentacion_descripcion, str):
            raise InvalidProductEmbeddingDocument(
                "presentacion_descripcion must be a string"
            )
        if not projection.presentacion_descripcion.strip() and not projection.presentacion_codigo.strip():
            raise InvalidProductEmbeddingDocument(
                "presentacion must be non-empty (both presentacion_codigo and presentacion_descripcion are empty)"
            )

    @staticmethod
    def _validate_aliases(
        aliases: tuple[ProductEmbeddingAliasInput, ...],
        target_producto_presentacion_id: int,
    ) -> None:
        for alias in aliases:
            if alias.scope not in _VALID_ALIAS_SCOPES:
                raise InvalidProductEmbeddingDocument(
                    "alias scope must be 'product' or 'product_presentacion'"
                )
            if alias.scope == "product_presentacion":
                if alias.id_producto_presentacion is None:
                    raise InvalidProductEmbeddingDocument(
                        "alias scope 'product_presentacion' requires "
                        "id_producto_presentacion"
                    )
                if alias.id_producto_presentacion != target_producto_presentacion_id:
                    raise InvalidProductEmbeddingDocument(
                        "alias scope 'product_presentacion' must point at "
                        "the target producto_presentacion_id"
                    )
            else:
                if alias.id_producto_presentacion is not None:
                    raise InvalidProductEmbeddingDocument(
                        "alias scope 'product' must not carry "
                        "id_producto_presentacion"
                    )

    @staticmethod
    def _resolve_presentation_text(
        projection: ProductEmbeddingCatalogProjection,
    ) -> str:
        if projection.presentacion_descripcion.strip():
            return projection.presentacion_descripcion.strip()
        if projection.presentacion_codigo.strip():
            return projection.presentacion_codigo.strip()
        raise InvalidProductEmbeddingDocument(
            "presentacion must be non-empty (both presentacion_codigo and presentacion_descripcion are empty)"
        )

    @staticmethod
    def _build_canonical(
        projection: ProductEmbeddingCatalogProjection,
        presentation_text: str,
    ) -> ProductEmbeddingDocument:
        source_text = f"{projection.producto_nombre} {presentation_text}"
        normalized = normalize_for_embedding(source_text)
        return ProductEmbeddingDocument(
            producto_id=projection.producto_id,
            producto_presentacion_id=projection.producto_presentacion_id,
            source_type="canonical",
            source_record_id=None,
            source_text=source_text,
            normalized_text=normalized,
            content_hash=_compute_content_hash(
                projection.producto_presentacion_id,
                "canonical",
                None,
                normalized,
            ),
        )

    def _build_description(
        self,
        projection: ProductEmbeddingCatalogProjection,
        presentation_text: str,
    ) -> ProductEmbeddingDocument | None:
        description = projection.producto_descripcion
        if description is None or not description.strip():
            return None
        canonical_source_text = (
            f"{projection.producto_nombre} {presentation_text}"
        )
        source_text = f"{canonical_source_text}. {description.strip()}."
        normalized = normalize_for_embedding(source_text)
        return ProductEmbeddingDocument(
            producto_id=projection.producto_id,
            producto_presentacion_id=projection.producto_presentacion_id,
            source_type="description",
            source_record_id=None,
            source_text=source_text,
            normalized_text=normalized,
            content_hash=_compute_content_hash(
                projection.producto_presentacion_id,
                "description",
                None,
                normalized,
            ),
        )

    @staticmethod
    def _build_alias_documents(
        aliases: tuple[ProductEmbeddingAliasInput, ...],
        projection: ProductEmbeddingCatalogProjection,
        presentation_text: str,
    ) -> list[ProductEmbeddingDocument]:
        applicable: list[ProductEmbeddingAliasInput] = []
        for alias in aliases:
            if not alias.activo:
                continue
            if alias.scope == "product" or alias.id_producto_presentacion == projection.producto_presentacion_id:
                applicable.append(alias)
        deduped = _dedupe_aliases(applicable)
        stable = sorted(
            deduped,
            key=lambda alias: (alias.alias_normalizado, alias.id),
        )
        documents: list[ProductEmbeddingDocument] = []
        for alias in stable:
            source_text = f"{alias.alias} {presentation_text}"
            normalized = normalize_for_embedding(source_text)
            documents.append(
                ProductEmbeddingDocument(
                    producto_id=projection.producto_id,
                    producto_presentacion_id=projection.producto_presentacion_id,
                    source_type="alias",
                    source_record_id=alias.id,
                    source_text=source_text,
                    normalized_text=normalized,
                    content_hash=_compute_content_hash(
                        projection.producto_presentacion_id,
                        "alias",
                        alias.id,
                        normalized,
                    ),
                )
            )
        return documents

    @staticmethod
    def _build_combined(
        projection: ProductEmbeddingCatalogProjection,
        presentation_text: str,
    ) -> ProductEmbeddingDocument:
        description = projection.producto_descripcion
        if description is not None and description.strip():
            source_text = (
                f"Categoría: {projection.categoria_nombre}. "
                f"Producto: {projection.producto_nombre}. "
                f"Descripción: {description.strip()}. "
                f"Presentación: {presentation_text}."
            )
        else:
            source_text = (
                f"Categoría: {projection.categoria_nombre}. "
                f"Producto: {projection.producto_nombre}. "
                f"Presentación: {presentation_text}."
            )
        normalized = normalize_for_embedding(source_text)
        return ProductEmbeddingDocument(
            producto_id=projection.producto_id,
            producto_presentacion_id=projection.producto_presentacion_id,
            source_type="combined",
            source_record_id=None,
            source_text=source_text,
            normalized_text=normalized,
            content_hash=_compute_content_hash(
                projection.producto_presentacion_id,
                "combined",
                None,
                normalized,
            ),
        )


def _dedupe_aliases(
    aliases: Iterable[ProductEmbeddingAliasInput],
) -> list[ProductEmbeddingAliasInput]:
    by_normalized: dict[str, ProductEmbeddingAliasInput] = {}
    for alias in aliases:
        key = alias.alias_normalizado
        existing = by_normalized.get(key)
        if existing is None or alias.id < existing.id:
            by_normalized[key] = alias
    return list(by_normalized.values())


def _compute_content_hash(
    producto_presentacion_id: int,
    source_type: ProductEmbeddingSourceType,
    source_record_id: int | None,
    normalized_text: str,
) -> str:
    raw = (
        f"{producto_presentacion_id}"
        f"{_HASH_SEPARATOR}{source_type}"
        f"{_HASH_SEPARATOR}{source_record_id if source_record_id is not None else ''}"
        f"{_HASH_SEPARATOR}{normalized_text}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "InvalidProductEmbeddingDocument",
    "ProductEmbeddingAliasInput",
    "ProductEmbeddingAliasScope",
    "ProductEmbeddingCatalogProjection",
    "ProductEmbeddingDocument",
    "ProductEmbeddingDocumentBuilder",
    "ProductEmbeddingSourceType",
]
