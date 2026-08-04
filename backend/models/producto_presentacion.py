from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.precio import Precio
    from backend.models.presentaciones import Presentacion
    from backend.models.producto import Producto
    from backend.models.producto_alias import ProductoAlias
    from backend.models.producto_presentacion_embedding import (
        ProductoPresentacionEmbedding,
    )


class ProductoPresentacion(Base):
    __tablename__ = "producto_presentaciones"

    __table_args__ = (
        UniqueConstraint(
            "id_producto",
            "id_presentacion",
            name="producto_presentacion_unico",
        ),
        CheckConstraint(
            "orden >= 0",
            name="orden_no_negativo",
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
        index=True,
    )

    id_presentacion: Mapped[int] = mapped_column(
        ForeignKey(
            "presentaciones.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    orden: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
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
        back_populates="presentaciones",
    )

    presentacion: Mapped["Presentacion"] = relationship(
        back_populates="productos_presentacion",
    )

    precios: Mapped[list["Precio"]] = relationship(
        back_populates="producto_presentacion",
    )

    aliases: Mapped[list["ProductoAlias"]] = relationship(
        back_populates="producto_presentacion",
        cascade="all, delete-orphan",
    )

    embeddings: Mapped[list["ProductoPresentacionEmbedding"]] = relationship(
        back_populates="producto_presentacion",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
