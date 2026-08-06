"""Canonical WhatsApp destination channel.

A ``CanalWhatsapp`` is the durable, provider-scoped destination-number
authority. It is independent of ``Comercio.whatsapp`` so that a shared
number (one destination, many commerces) can be modeled without
conflating commerce contact data with provider transport.

Channels are either:

* ``dedicated`` — exactly one exclusive ``Comercio`` reference while
  active; used for direct resolution from provider + destination.
* ``shared`` — no exclusive ``Comercio`` reference; members join via
  ``ComercioCanalCompartido``.

The direct ``id_comercio_exclusivo`` foreign key is intentionally not a
generic many-to-many relation: exclusive ownership must be directly
representable so the service can reject dedicated channels that try to
receive shared memberships and shared channels that try to carry an
exclusive ``Comercio``.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.comercio import Comercio
    from backend.models.comercio_canal_compartido import (
        ComercioCanalCompartido,
    )


class CanalWhatsappMode(str, enum.Enum):
    DEDICATED = "dedicated"
    SHARED = "shared"


class CanalWhatsapp(Base):
    __tablename__ = "canales_whatsapp"

    __table_args__ = (
        CheckConstraint(
            "provider <> ''",
            name="canal_whatsapp_provider_no_vacio",
        ),
        CheckConstraint(
            "destination_e164 <> ''",
            name="canal_whatsapp_destination_no_vacio",
        ),
        CheckConstraint(
            "destination_e164 NOT LIKE 'whatsapp:%'",
            name="canal_whatsapp_destination_no_prefijo",
        ),
        CheckConstraint(
            "destination_e164 LIKE '+%'",
            name="canal_whatsapp_destination_e164",
        ),
        CheckConstraint(
            (
                "(mode = 'dedicated' AND id_comercio_exclusivo IS NOT NULL) "
                "OR (mode = 'shared' AND id_comercio_exclusivo IS NULL)"
            ),
            name="canal_whatsapp_mode_comercio_exclusivo_chk",
        ),
        Index(
            "canales_whatsapp_provider_destino_unico",
            "provider",
            "destination_e164",
            unique=True,
            postgresql_where=text("activo = true"),
        ),
        Index(
            "ix_canales_whatsapp_id_comercio_exclusivo",
            "id_comercio_exclusivo",
        ),
        Index(
            "ix_canales_whatsapp_activo",
            "activo",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    destination_e164: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    mode: Mapped[CanalWhatsappMode] = mapped_column(
        Enum(
            CanalWhatsappMode,
            name="canal_whatsapp_mode",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    id_comercio_exclusivo: Mapped[int | None] = mapped_column(
        ForeignKey(
            "comercios.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
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

    fecha_baja: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    comercio_exclusivo: Mapped[Comercio | None] = relationship(
        "Comercio",
        foreign_keys=[id_comercio_exclusivo],
    )

    membresias_compartidas: Mapped[list[ComercioCanalCompartido]] = relationship(
        back_populates="canal",
        cascade="all, delete-orphan",
    )


__all__ = ["CanalWhatsapp", "CanalWhatsappMode"]