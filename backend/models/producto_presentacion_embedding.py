"""SQLAlchemy model for per-document product-presentation embeddings.

Subphase 4.6 evolves the persistence boundary from one aggregate row
per ``(id_producto_presentacion, modelo)`` to one row per semantic
document. Each row carries a ``source_type`` (``canonical`` /
``description`` / ``alias`` / ``combined``), an optional
``source_record_id`` (the alias row id for ``alias`` rows, ``NULL`` for
every other source type), the original ``source_text`` and the
deterministic ``normalized_text`` and ``content_hash`` produced by the
pure ``ProductEmbeddingDocumentBuilder``, an ``embedding_status`` from
the closed set ``pending|ready|failed|stale|inactive``, an ``activo``
flag, and an optional ``last_error``.

The ``EmbeddingStatus`` enum is a ``str, enum.Enum`` whose values ARE
the lowercase strings; the closed set is enforced by the table-level
``embedding_status_chk`` ``CHECK`` constraint enforced at the database
level. There is exactly one database representation.

Two PostgreSQL partial unique indexes replace the legacy
``(id_producto_presentacion, modelo)`` aggregate uniqueness rule:

- ``uq_embedding_doc_null_source`` covers ``canonical`` / ``description``
  / ``combined`` (one slot each per presentation per model).
- ``uq_embedding_doc_alias`` covers ``alias`` rows (one slot per alias
  per presentation per model).

The ``vector`` column is nullable because non-ready states may not have
a vector; the ``ready_vector_chk`` enforces the ``ready → vector not
null`` invariant.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.config.settings import load_settings
from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.producto_presentacion import ProductoPresentacion


EMBEDDING_DIMENSION = load_settings().embedding_dimension


class EmbeddingStatus(str, enum.Enum):
    """Status state-machine values for per-document embeddings.

    The Python enum value IS the lowercase string so SQLAlchemy persists
    the lowercase representation directly. The closed set is enforced by
    the table-level ``embedding_status_chk`` ``CHECK`` constraint.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    INACTIVE = "inactive"


class ProductoPresentacionEmbedding(Base):
    __tablename__ = "producto_presentacion_embeddings"

    __table_args__ = (
        Index(
            "uq_embedding_doc_null_source",
            "id_producto_presentacion",
            "modelo",
            "source_type",
            unique=True,
            postgresql_where=text("source_record_id IS NULL"),
        ),
        Index(
            "uq_embedding_doc_alias",
            "id_producto_presentacion",
            "modelo",
            "source_type",
            "source_record_id",
            unique=True,
            postgresql_where=text("source_record_id IS NOT NULL"),
        ),
        CheckConstraint(
            "source_type IN ('canonical','description','alias','combined')",
            name="source_type_chk",
        ),
        CheckConstraint(
            (
                "(source_type = 'alias' AND source_record_id IS NOT NULL) "
                "OR (source_type <> 'alias' AND source_record_id IS NULL)"
            ),
            name="source_record_id_alias_chk",
        ),
        CheckConstraint(
            "embedding_status <> 'ready' OR vector IS NOT NULL",
            name="ready_vector_chk",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_chk",
        ),
        CheckConstraint(
            "length(btrim(source_text)) > 0",
            name="source_text_nonempty_chk",
        ),
        CheckConstraint(
            "length(btrim(normalized_text)) > 0",
            name="normalized_text_nonempty_chk",
        ),
        CheckConstraint(
            "embedding_status IN ('pending','ready','failed','stale','inactive')",
            name="embedding_status_chk",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_producto_presentacion: Mapped[int] = mapped_column(
        ForeignKey(
            "producto_presentaciones.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    vector: Mapped[list[float] | None] = mapped_column(
        VECTOR(EMBEDDING_DIMENSION),
        nullable=True,
    )

    modelo: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )

    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    source_record_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    source_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    embedding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EmbeddingStatus.PENDING.value,
        server_default=text("'pending'"),
    )

    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    fecha_alta: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    fecha_ultima_modificacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    producto_presentacion: Mapped[ProductoPresentacion] = relationship(
        back_populates="embeddings",
    )


__all__ = [
    "EMBEDDING_DIMENSION",
    "EmbeddingStatus",
    "ProductoPresentacionEmbedding",
]
