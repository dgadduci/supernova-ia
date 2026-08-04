from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.config.settings import load_settings
from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.producto_presentacion import ProductoPresentacion


EMBEDDING_DIMENSION = load_settings().embedding_dimension


class ProductoPresentacionEmbedding(Base):
    __tablename__ = "producto_presentacion_embeddings"

    __table_args__ = (
        UniqueConstraint(
            "id_producto_presentacion",
            "modelo",
            name="producto_presentacion_embedding_unico",
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

    vector: Mapped[list[float]] = mapped_column(
        VECTOR(EMBEDDING_DIMENSION),
        nullable=False,
    )

    modelo: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
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

    producto_presentacion: Mapped["ProductoPresentacion"] = relationship(
        back_populates="embeddings",
    )


__all__ = ["EMBEDDING_DIMENSION", "ProductoPresentacionEmbedding"]
