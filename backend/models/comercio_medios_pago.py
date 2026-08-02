from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class ComercioMedioPago(Base):
    __tablename__ = "comercio_medios_pago"

    __table_args__ = (
        UniqueConstraint(
            "id_comercio",
            "id_medio_pago",
            name="comercio_medio_pago_unico",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_comercio: Mapped[int] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    id_medio_pago: Mapped[int] = mapped_column(
        ForeignKey(
            "medios_pago.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    titular: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    alias: Mapped[str | None] = mapped_column(
        String(100),
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

    comercio: Mapped["Comercio"] = relationship(
        back_populates="medios_pago",
    )

    medio_pago: Mapped["MediosPago"] = relationship(
        back_populates="comercios",
    )
