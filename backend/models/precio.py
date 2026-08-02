from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class Precio(Base):
    __tablename__ = "producto_precios"

    __table_args__ = (
        CheckConstraint(
            "precio >= 0",
            name="precio_no_negativo",
        ),
        Index(
            "id_producto_presentacion",
            "id_producto_presentacion",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_producto_presentacion: Mapped[int] = mapped_column(
        ForeignKey(
            "producto_presentaciones.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    precio: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    fecha_alta: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    producto_presentacion: Mapped["ProductoPresentacion"] = relationship(
        back_populates="precios",
    )
