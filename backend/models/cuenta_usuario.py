"""Application-owned account identity for the commerce owner.

The :class:`CuentaUsuario` row is the NovaOrders-side mirror of a
Supabase Auth subject. Phase 2 only ever produces a validated
external subject from the Supabase JWT; Phase 3 introduces the
persistence boundary so the owner surface can resolve or create the
local account for that exact subject.

The model is intentionally minimal:

* ``id`` — internal surrogate primary key.
* ``supabase_subject`` — immutable, unique external identifier
  extracted from the validated ``sub`` claim. The field is the only
  external identity input stored on the row: no email, no provider
  profile metadata, no token, no audience or issuer is duplicated
  here. The uniqueness constraint is the durable cross-request
  resolution key.
* ``activo`` — soft-deactivation flag. The flag allows an operator
  to revoke the local account without dropping the row; the wizard
  refuses to load or save a draft for an inactive account.
* ``fecha_alta`` and ``fecha_ultima_modificacion`` — UTC creation
  and update timestamps maintained by SQLAlchemy server defaults.
* ``fecha_baja`` — optional UTC revocation timestamp. The column
  stays ``NULL`` for active accounts and is set when an operator
  revokes the account; uniqueness of the external subject is
  preserved across deactivation cycles.

The model introduces ``email``, provider metadata or any Supabase
profile mirror intentionally: Phase 3 keeps the account identity
to its source-of-truth external subject and stores nothing else.
A future phase that requires an email must store it on a dedicated
column after a separate approval and migration, never by reusing
this table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class CuentaUsuario(Base):
    __tablename__ = "cuentas_usuario"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    supabase_subject: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
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


__all__ = ["CuentaUsuario"]
