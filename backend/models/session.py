import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base
from backend.models.cliente import Cliente
from backend.models.comercio import Comercio


class EstadoSession(enum.Enum):
    ACTIVA = "activa"
    CERRADA = "cerrada"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    id_comercio: Mapped[int] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    id_cliente: Mapped[int] = mapped_column(
        ForeignKey(
            "clientes.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    id_pedido: Mapped[int | None] = mapped_column(
        ForeignKey(
            "pedidos.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    datetime_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    datetime_ultimo_movimiento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    estado_session: Mapped[EstadoSession] = mapped_column(
        Enum(
            EstadoSession,
            name="estado_session",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=EstadoSession.ACTIVA,
        server_default=EstadoSession.ACTIVA.value,
    )

    pending_intents: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=lambda: {},
        server_default=text("'{}'::json"),
    )

    context_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )

    comercio: Mapped[Comercio] = relationship(Comercio)

    cliente: Mapped[Cliente] = relationship(Cliente)

    pedido: Mapped["Pedido | None"] = relationship(
        "Pedido",
        primaryjoin="Session.id_pedido == Pedido.id",
        foreign_keys="Session.id_pedido",
        post_update=True,
    )


from backend.models.pedido import Pedido  # noqa: E402  (circular import resolution)