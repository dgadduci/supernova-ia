"""Channel-scoped customer routing context.

``ContextoClienteCanalWhatsapp`` is the sole Phase-5.2 pre-commerce
state, extended in Phase 5.3 to support manual commerce selection and
explicit switching on an active shared channel. It records that an
existing client has activated a ``ComercioCanalCompartido`` membership
on a shared ``CanalWhatsapp``, remembers the caller-supplied raw
original inbound text so a later phase can route it through the
business pipeline without losing the raw envelope, and holds an
optional pending switch target.

The pending target (``comercio_id_cambio_pendiente``) is only ever a
proposed commerce — never an authority for processing. It is set by an
explicit switch request and consumed (moved to
``comercio_id_seleccionado`` or cleared) only by an explicit
confirmation or cancellation. The existing selection is the only
selection the rest of the system can observe; commerce replacement
is gated by confirmation.

The context is intentionally keyed by the WhatsApp channel plus the
existing client: one customer may interact with multiple provider
destinations and each destination requires its own commerce selection.
The unique constraint on ``(canal_id, cliente_id)`` is unconditional:
a customer has at most one routing context per shared destination.

The context is NOT a ``Session``: ``Session`` rows require a non-null
``id_comercio`` and belong to the existing order flow. This table is
intentionally independent of ``Session`` so the activation step can
choose a commerce without first opening an order session.

Foreign keys use ``RESTRICT`` on every reference. ``canal_id`` and
``cliente_id`` MUST NOT cascade-delete away the routing context: an
operator that deletes a channel or a client must explicitly remove
their routing contexts first so the pending original message is never
silently lost.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class ContextoClienteCanalWhatsapp(Base):
    __tablename__ = "contextos_clientes_canales_whatsapp"

    __table_args__ = (
        UniqueConstraint(
            "canal_id",
            "cliente_id",
            name="contextos_clientes_canales_whatsapp_canal_cliente_unico",
        ),
        Index(
            "ix_contextos_clientes_canales_whatsapp_cambio_pendiente",
            "comercio_id_cambio_pendiente",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    canal_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canales_whatsapp.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    cliente_id: Mapped[int] = mapped_column(
        ForeignKey(
            "clientes.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    comercio_id_seleccionado: Mapped[int | None] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    comercio_id_cambio_pendiente: Mapped[int | None] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    mensaje_original_pendiente: Mapped[str | None] = mapped_column(
        Text,
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


__all__ = ["ContextoClienteCanalWhatsapp"]
