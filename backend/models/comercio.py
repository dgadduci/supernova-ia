from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base
from backend.models.estado_comercio import EstadoComercio


class Comercio(Base):
    __tablename__ = "comercios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    nombre_fantasia: Mapped[str] = mapped_column(String(150), nullable=False)
    nombre_corto: Mapped[str] = mapped_column(String(80), nullable=False)
    razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    cuit: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    whatsapp: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)

    calle: Mapped[str] = mapped_column(String(150), nullable=False)
    numero: Mapped[str] = mapped_column(String(20), nullable=False)
    piso_departamento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    localidad: Mapped[str] = mapped_column(String(100), nullable=False)
    provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo_postal: Mapped[str | None] = mapped_column(String(20), nullable=True)

    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)

    estado_id: Mapped[int] = mapped_column(ForeignKey("estado_comercio.id"), nullable=False)
    estado: Mapped[EstadoComercio] = relationship(EstadoComercio)

    zona_horaria: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="America/Argentina/Buenos_Aires",
        server_default="America/Argentina/Buenos_Aires",
    )
    moneda: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="ARS",
        server_default="ARS",
    )
    idioma: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="es-AR",
        server_default="es-AR",
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
    fecha_baja: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    metodos_entrega: Mapped[list["ComercioMetodoEntrega"]] = relationship(
        back_populates="comercio",
    )

    medios_pago: Mapped[list["ComercioMedioPago"]] = relationship(
        back_populates="comercio",
    )
