from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class ProductoAlias(Base):
    __tablename__ = "producto_aliases"

    __table_args__ = (
        Index(
            "ix_producto_aliases_id_producto",
            "id_producto",
        ),
        Index(
            "ix_producto_aliases_id_producto_presentacion",
            "id_producto_presentacion",
        ),
        Index(
            "ix_producto_aliases_alias_normalizado",
            "alias_normalizado",
        ),
        Index(
            "ix_producto_aliases_activo",
            "activo",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_producto: Mapped[int] = mapped_column(
        ForeignKey(
            "productos.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    id_producto_presentacion: Mapped[int | None] = mapped_column(
        ForeignKey(
            "producto_presentaciones.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    alias: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    alias_normalizado: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
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

    producto: Mapped["Producto"] = relationship(
        back_populates="aliases",
    )

    producto_presentacion: Mapped["ProductoPresentacion | None"] = relationship(
        back_populates="aliases",
    )


__all__ = ["ProductoAlias"]
