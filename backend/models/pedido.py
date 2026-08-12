import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base
from backend.models.medios_pago import MediosPago
from backend.models.metodos_entrega import MetodosEntrega

if TYPE_CHECKING:
    from backend.models.session import Session


class EstadoPedido(enum.Enum):
    BORRADOR = "borrador"
    INGRESADO = "ingresado"
    PREPARACION = "preparacion"
    TERMINADO = "terminado"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_session: Mapped[int] = mapped_column(
        ForeignKey(
            "sessions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    id_medio_pago: Mapped[int | None] = mapped_column(
        ForeignKey(
            "medios_pago.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    id_metodo_entrega: Mapped[int | None] = mapped_column(
        ForeignKey(
            "metodos_entrega.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    datetime_entrega_programada: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    estado_pedido: Mapped[EstadoPedido] = mapped_column(
        Enum(
            EstadoPedido,
            name="estado_pedido",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=EstadoPedido.BORRADOR,
        server_default=EstadoPedido.BORRADOR.value,
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

    observaciones: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    medio_pago: Mapped[MediosPago | None] = relationship(MediosPago)

    metodo_entrega: Mapped[MetodosEntrega | None] = relationship(MetodosEntrega)

    session: Mapped["Session"] = relationship(
        "Session",
        primaryjoin="Pedido.id_session == Session.id",
        foreign_keys="Pedido.id_session",
    )