from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class MetodosEntrega(Base):
    __tablename__ = "metodos_entrega"

    __table_args__ = (
        CheckConstraint(
            "orden >= 0",
            name="orden_no_negativo",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    codigo: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
    )

    descripcion: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    orden: Mapped[int] = mapped_column(
        Integer,
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

    comercios: Mapped[list["ComercioMetodoEntrega"]] = relationship(
        back_populates="metodo_entrega",
    )
