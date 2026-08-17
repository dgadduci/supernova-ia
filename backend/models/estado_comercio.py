import enum

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class EstadoComercioModoOperacion(str, enum.Enum):
    """Typed operating mode for an :class:`EstadoComercio` row.

    The policy interprets ONLY this mode. The ``codigo`` and
    ``descripcion`` fields are stable identity / display surfaces;
    no caller compares them as a behavior branch.
    """

    HABILITADO = "habilitado"
    BLOQUEADO = "bloqueado"
    PRUEBA = "prueba"


class EstadoComercio(Base):
    __tablename__ = "estado_comercio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    descripcion: Mapped[str] = mapped_column(String(150), nullable=False)
    modo_operacion: Mapped[EstadoComercioModoOperacion] = mapped_column(
        Enum(
            EstadoComercioModoOperacion,
            name="estado_comercio_modo_operacion",
            values_callable=lambda enum_cls: [
                member.value for member in enum_cls
            ],
        ),
        nullable=False,
    )
    seleccionable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )


__all__ = [
    "EstadoComercio",
    "EstadoComercioModoOperacion",
]