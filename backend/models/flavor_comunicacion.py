"""Global communication flavor catalog.

A ``FlavorComunicacion`` is a system-managed, commerce-agnostic
communication style profile. The catalog is global: every existing and
new commerce references exactly one active global flavor through
``Comercio.flavor_comunicacion_id``. Commerces cannot create, edit or
describe flavors and they cannot supply an ``instruccion_llm`` value.

The ``instruccion_llm`` column is a backend-only directive intended for
the future response-embellishment phase. It is never exposed through
any router, schema, diagnostic, log message or exception detail.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

if TYPE_CHECKING:
    from backend.models.comercio import Comercio


class FlavorComunicacion(Base):
    __tablename__ = "flavors_comunicacion"

    __table_args__ = (
        CheckConstraint(
            "codigo <> ''",
            name="flavor_comunicacion_codigo_no_vacio",
        ),
        CheckConstraint(
            "nombre <> ''",
            name="flavor_comunicacion_nombre_no_vacio",
        ),
        CheckConstraint(
            "descripcion <> ''",
            name="flavor_comunicacion_descripcion_no_vacia",
        ),
        CheckConstraint(
            "length(instruccion_llm) > 0",
            name="flavor_comunicacion_instruccion_llm_no_vacia",
        ),
        CheckConstraint(
            "version > 0",
            name="flavor_comunicacion_version_positiva",
        ),
        UniqueConstraint(
            "codigo",
            name="flavors_comunicacion_codigo_unico",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    codigo: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    nombre: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    descripcion: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    instruccion_llm: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
    )

    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
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

    comercios: Mapped[list[Comercio]] = relationship(
        back_populates="flavor_comunicacion",
    )


__all__ = ["FlavorComunicacion"]
