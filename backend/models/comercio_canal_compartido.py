"""Shared-channel membership and permanent routing-code reservation.

``ComercioCanalCompartido`` models only one thing: a commerce's
membership in a shared WhatsApp channel, identified by an opaque
normalized routing code (e.g. a QR / short-link slug surfaced to the
customer).

Dedicated channels MUST NOT have memberships — the service rejects the
attempt. The direct foreign key from a dedicated ``CanalWhatsapp`` to a
single exclusive commerce is the dedicated-channel ownership path;
mixing the two models would break commerce isolation.

The ``(canal_id, routing_code_normalized)`` uniqueness rule has NO
active predicate: deactivation revokes a code and prevents a stale
link/QR from being reassigned to another commerce. Historical codes
remain reserved for the full channel history.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.canal_whatsapp import CanalWhatsapp
    from backend.models.comercio import Comercio


class ComercioCanalCompartido(Base):
    __tablename__ = "comercios_canales_compartidos"

    __table_args__ = (
        CheckConstraint(
            "routing_code <> ''",
            name="comercio_canal_compartido_routing_code_no_vacio",
        ),
        CheckConstraint(
            "routing_code_normalizado <> ''",
            name=(
                "comercio_canal_compartido_routing_code_normalizado_no_vacio"
            ),
        ),
        Index(
            "ix_comercios_canales_compartidos_canal_id",
            "canal_id",
        ),
        Index(
            "ix_comercios_canales_compartidos_comercio_id",
            "comercio_id",
        ),
        Index(
            "ix_comercios_canales_compartidos_activo",
            "activo",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    canal_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canales_whatsapp.id",
            ondelete="CASCADE",
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

    routing_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    routing_code_normalizado: Mapped[str] = mapped_column(
        String(80),
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

    canal: Mapped[CanalWhatsapp] = relationship(
        back_populates="membresias_compartidas",
    )

    comercio: Mapped[Comercio] = relationship()


__all__ = ["ComercioCanalCompartido"]