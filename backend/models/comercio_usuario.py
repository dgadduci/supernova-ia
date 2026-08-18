"""Application-owned commerce membership row.

The :class:`ComercioUsuario` row is the boundary that authorizes a
``CuentaUsuario`` over the exact ``Comercio`` it is meant to
operate. The Phase 4A atomic completion transaction stages the
single ``OWNER`` membership for the freshly-created commerce in
the same caller-owned unit-of-work as the commerce row and the
draft's terminal transition; no other row in this table exists at
that point.

The model is intentionally narrow:

* ``id`` — internal surrogate primary key.
* ``cuenta_usuario_id`` and ``comercio_id`` — RESTRICT foreign keys
  to the application-owned account and commerce rows. ``RESTRICT``
  is the documented invariant: a commerce cannot be deleted while
  a membership references it, and an account cannot be deleted
  while its membership is live.
* ``rol`` — closed ``OWNER`` string. The database ``CHECK`` plus
  the unique ``(comercio_id, rol)`` index guarantee the closed
  set and the "exactly one OWNER per commerce" invariant.
* ``UNIQUE (cuenta_usuario_id, comercio_id)`` — an account can be
  a member of a specific commerce at most once.
* ``activo`` — soft-revocation flag. Phase 4A always stages the
  membership with ``activo = True``.
* ``fecha_alta``, ``fecha_ultima_modificacion`` and optional
  ``fecha_baja`` — UTC audit timestamps maintained by SQLAlchemy
  server defaults.

The model never references payments, deliveries, channels,
catalogue or trial state. Membership transitions beyond the
single ``OWNER`` row Phase 4A creates stay outside the current
implementation and are not modelled here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class ComercioUsuario(Base):
    __tablename__ = "comercio_usuarios"

    __table_args__ = (
        CheckConstraint(
            "rol = 'OWNER'",
            name="comercio_usuarios_rol_owner",
        ),
        UniqueConstraint(
            "cuenta_usuario_id",
            "comercio_id",
            name="comercio_usuarios_cuenta_comercio_unique",
        ),
        UniqueConstraint(
            "comercio_id",
            "rol",
            name="comercio_usuarios_comercio_rol_unique",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )

    cuenta_usuario_id: Mapped[int] = mapped_column(
        ForeignKey("cuentas_usuario.id", ondelete="RESTRICT"),
        nullable=False,
    )

    comercio_id: Mapped[int] = mapped_column(
        ForeignKey("comercios.id", ondelete="RESTRICT"),
        nullable=False,
    )

    rol: Mapped[str] = mapped_column(String(20), nullable=False)

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


__all__ = ["ComercioUsuario"]
