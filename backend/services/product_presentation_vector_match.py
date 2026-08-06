"""Typed result for the product-presentation vector search service.

Subphase 4.9 introduces a frozen ``ProductPresentationVectorMatch``
dataclass that the search service returns. The dataclass is the
contract between the pgvector distance query and any future caller
(recognizer, customer-message flow, or hybrid routing).

The dataclass exposes ONLY three fields:

- ``id_producto_presentacion``: the unique presentation identifier.
- ``score``: cosine similarity (``1 - cosine_distance``), higher means
  more similar.
- ``source_type``: the document source that won the per-presentation
  best-match window (``canonical`` / ``description`` / ``alias`` /
  ``combined``).

The dataclass is intentionally minimal: it MUST NOT carry the raw
vector, the original ``source_text``, the ``normalized_text``, the
``content_hash``, the ``last_error``, the underlying SQLAlchemy model
instance, the raw ``distance`` value, internal exception traces, or any
persisted ``Settings`` field. The dataclass is a plain ``frozen=True``
``@dataclass``; it MUST NOT be a Pydantic model, a SQLAlchemy ORM
model, or a class with side effects in ``__post_init__``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductPresentationVectorMatch:
    """Typed one-line result from the product-presentation vector search.

    Instances are immutable: assigning to any field raises
    ``dataclasses.FrozenInstanceError``. The dataclass is the only
    public shape the search service returns to its callers.
    """

    id_producto_presentacion: int
    score: float
    source_type: str


__all__ = ["ProductPresentationVectorMatch"]