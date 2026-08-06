"""Phase-5.4 provider-message receipt.

A ``RecepcionMensajeProveedor`` is the durable, idempotent committed
boundary that proves a provider has delivered one message to this
system. The receipt is keyed by the unique pair of a normalized
provider identifier and the opaque provider-issued receipt identifier;
no other field participates in the uniqueness boundary, so equivalent
deliveries (including retries that arrive after the first commit)
collapse onto the same row.

The receipt is the authoritative proof that a provider message has
been processed exactly once. The first valid claim atomically
commits alongside the conversation session and the existing message
pipeline in the same transaction so the receipt can never exist
without its companion effects. A duplicate committed receipt
returns ``already_processed`` and never re-invokes the pipeline.

The model intentionally stores ONLY the opaque receipt identity and
the safe relational audit fields (channel, client and commerce ids
plus the committed timestamp). Raw message text, outbound delivery
state, retry counters and response payloads belong to later phases
and are deliberately not persisted on this row.

Foreign keys are restrictive so an operator cannot delete a channel,
client or commerce while a committed receipt still references it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class RecepcionMensajeProveedor(Base):
    __tablename__ = "recepciones_mensajes_proveedor"

    __table_args__ = (
        UniqueConstraint(
            "proveedor",
            "identificador_recepcion",
            name="recepciones_mensajes_proveedor_proveedor_recepcion_unico",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    proveedor: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    identificador_recepcion: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
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

    comercio_id: Mapped[int] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    fecha_recepcion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["RecepcionMensajeProveedor"]
