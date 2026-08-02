from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.pedido import Pedido
    from backend.models.producto_presentacion import ProductoPresentacion


class PedidoProducto(Base):
    __tablename__ = "pedidos_productos"

    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        UniqueConstraint(
            "id_pedido",
            "id_producto_presentacion",
            name="uq_pedido_producto_presentacion",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_pedido: Mapped[int] = mapped_column(
        ForeignKey(
            "pedidos.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    id_producto_presentacion: Mapped[int] = mapped_column(
        ForeignKey(
            "producto_presentaciones.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    cantidad: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    precio_unitario: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    observaciones: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    pedido: Mapped["Pedido"] = relationship("Pedido")

    producto_presentacion: Mapped["ProductoPresentacion"] = relationship(
        "ProductoPresentacion"
    )