"""Private per-account draft for the self-service onboarding wizard.

The :class:`BorradorOnboardingComercio` row is the NovaOrders-side
workspace where an authenticated owner stages the basic commerce
data required by the eventual ``Comercio`` create transaction. It
is private to its owning account and is *not* an operational
record: it carries no lifecycle, provider, channel, payment,
delivery, trial or catalogue data.

The model is intentionally narrow:

* ``id`` — internal surrogate primary key.
* ``cuenta_usuario_id`` — internal owner foreign key with a
  unique constraint. The uniqueness is what enforces exactly-one
  draft per account; the application MUST never disable the unique
  index or replace it with an optional relationship.
* ``slug`` — nullable text column required by the Phase 4A
  completion transaction. The column is nullable on purpose so
  Phase 3 drafts survive the upgrade; the wizard saves enforce
  non-empty server-side and the completion transaction refuses
  to proceed while ``slug`` is ``NULL`` or blank. Uniqueness is
  derived from the canonical ``comercios.slug`` unique index at
  completion time rather than from the draft table.
* ``version`` — monotonically incrementing counter used as the
  optimistic-concurrency token. The wizard embeds the loaded value
  in the form and re-sends it on every ``POST``; the repository
  rejects a save whose ``version`` does not match the row to
  prevent two concurrent tabs from silently overwriting each
  other.
* ``comercio_id`` and ``completado_en`` — terminal-only fields
  populated exclusively by the Phase 4A completion transaction.
  The two columns are jointly constrained by a paired-nullability
  check so the database itself rejects any row where one column
  is set without the other. ``comercio_id`` also carries a unique
  constraint so the same commerce cannot be referenced by more
  than one draft.
* ``fecha_alta`` and ``fecha_ultima_modificacion`` — UTC creation
  and update timestamps maintained by SQLAlchemy server defaults.
* ``nombre_fantasia`` / ``nombre_corto`` / ``razon_social`` /
  ``cuit`` / ``whatsapp`` / ``calle`` / ``numero`` /
  ``piso_departamento`` / ``localidad`` / ``provincia`` /
  ``codigo_postal`` — the closed set of basic-commerce fields the
  Phase 4 completion transaction consumes. They mirror the
  canonical ``Comercio`` columns for the same names so the future
  atomic create does not need to remap.
* ``completo`` — server-derived flag set by the wizard once every
  documented required basic field holds a non-empty stripped
  value. The flag is never accepted from the form.

The draft model never references ``comercios`` or
``comercio_usuarios`` in the wizard surface — the application
*does* reference ``comercios.id`` via the terminal ``comercio_id``
column, with the foreign key restricted so the draft cannot
silently outlive its commerce.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class BorradorOnboardingComercio(Base):
    __tablename__ = "borrador_onboarding_comercio"

    __table_args__ = (
        UniqueConstraint(
            "cuenta_usuario_id",
            name="borrador_onboarding_comercio_cuenta_usuario_unique",
        ),
        UniqueConstraint(
            "comercio_id",
            name="borrador_onboarding_comercio_comercio_id_unique",
        ),
        CheckConstraint(
            "(comercio_id IS NULL) = (completado_en IS NULL)",
            name=(
                "borrador_onboarding_comercio_"
                "comercio_id_completado_en_paired"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    cuenta_usuario_id: Mapped[int] = mapped_column(
        ForeignKey("cuentas_usuario.id", ondelete="RESTRICT"),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    completo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    slug: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )

    nombre_fantasia: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )
    nombre_corto: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    razon_social: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    cuit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    calle: Mapped[str | None] = mapped_column(String(150), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    piso_departamento: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    localidad: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    provincia: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    codigo_postal: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )

    comercio_id: Mapped[int | None] = mapped_column(
        ForeignKey("comercios.id", ondelete="RESTRICT"),
        nullable=True,
    )

    completado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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


__all__ = ["BorradorOnboardingComercio"]
