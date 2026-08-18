"""add Phase 4A ComercioUsuario and terminal onboarding draft columns

Revision ID: b5f47a4c19d3
Revises: a0e1f2d3c4b5
Create Date: 2026-08-18 20:00:00.000000

The ``add-commerce-self-service-onboarding`` change Phase 4A
introduces the membership boundary and the atomic completion
transaction that consumes a private owner draft. The migration is
intentionally additive — it adds two narrow tables/columns without
touching any historical commerce, order, payment, channel, trial
or catalogue row.

Upgrade contract:

1. Augment ``borrador_onboarding_comercio`` with three columns:

   * ``slug`` — nullable text (the wizard validates it non-empty
     server-side; uniqueness is enforced by the canonical
     ``comercios.slug`` unique index at completion time). The
     column is nullable on purpose so existing drafts survive the
     upgrade; Phase 4A completion refuses to proceed while the
     column is ``NULL``.

   * ``comercio_id`` — nullable foreign key to ``comercios.id``
     with ``RESTRICT`` on delete plus a unique constraint. The
     unique index is the durable guarantee that the same owner
     draft can produce at most one commerce.

   * ``completado_en`` — nullable timestamp with timezone. The
     timestamp and the ``comercio_id`` are jointly coordinated by
     a paired-nullability check constraint so the database itself
     rejects any row where one column is set without the other.

2. Add the ``comercio_usuarios`` table — the application-owned
   membership boundary between a ``CuentaUsuario`` and a
   ``Comercio``. The table carries:

   * RESTRICT foreign keys to both ``cuentas_usuario.id`` and
     ``comercios.id``.
   * A ``rol`` string column closed by a ``CHECK (rol = 'OWNER')``
     constraint, matching the OpenSpec Phase 4A "closed OWNER
     role" invariant.
   * ``UNIQUE (cuenta_usuario_id, comercio_id)`` — every account
     can be a member of a specific commerce at most once.
   * ``UNIQUE (comercio_id, rol)`` — Phase 4A completion creates
     exactly one OWNER membership per new commerce.
   * ``activo`` flag, audit timestamps and optional ``fecha_baja``
     so the membership lifecycle matches the
     ``CuentaUsuario`` / ``Comercio`` audit surface.

3. None of ``comercios``, ``pedidos``, ``sessions``, ``clientes``,
   ``canales``, ``medios_pago``, ``metodos_entrega``, ``productos``
   or any catalogue/association row is touched. The migration
   adds tables/columns only.

Downgrade contract:

1. Drop ``comercio_usuarios`` first so its foreign keys cannot
   block subsequent drops.
2. Drop the paired-nullability check, then ``completado_en``,
   then the unique constraint / foreign key on ``comercio_id``,
   then ``comercio_id`` and finally ``slug`` from
   ``borrador_onboarding_comercio``.

The downgrade drops the new surface only; historical commerce /
order data is preserved on every step.

Idempotency: every step uses straight ``op.create_table`` /
``op.add_column`` / ``op.drop_table`` / ``op.drop_column``
calls. The migration is non-destructive on existing rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b5f47a4c19d3"
down_revision: str | Sequence[str] | None = "a0e1f2d3c4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "borrador_onboarding_comercio"


def upgrade() -> None:
    """Create the Phase 4A membership table and extend the draft."""
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(
            sa.Column(
                "slug",
                sa.String(length=150),
                nullable=True,
            )
        )

    op.add_column(
        _TABLE,
        sa.Column(
            "comercio_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "borrador_onboarding_comercio_comercio_id_fkey",
        _TABLE,
        "comercios",
        ["comercio_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "borrador_onboarding_comercio_comercio_id_unique",
        _TABLE,
        ["comercio_id"],
    )

    op.add_column(
        _TABLE,
        sa.Column(
            "completado_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "borrador_onboarding_comercio_comercio_id_completado_en_paired",
        _TABLE,
        "(comercio_id IS NULL) = (completado_en IS NULL)",
    )

    op.create_table(
        "comercio_usuarios",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "cuenta_usuario_id",
            sa.Integer(),
            sa.ForeignKey(
                "cuentas_usuario.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "comercio_id",
            sa.Integer(),
            sa.ForeignKey(
                "comercios.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "rol",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "fecha_alta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "fecha_baja",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "rol = 'OWNER'",
            name="comercio_usuarios_rol_owner",
        ),
        sa.UniqueConstraint(
            "cuenta_usuario_id",
            "comercio_id",
            name="comercio_usuarios_cuenta_comercio_unique",
        ),
        sa.UniqueConstraint(
            "comercio_id",
            "rol",
            name="comercio_usuarios_comercio_rol_unique",
        ),
    )
    op.create_index(
        "comercio_usuarios_cuenta_usuario_id_idx",
        "comercio_usuarios",
        ["cuenta_usuario_id"],
    )
    op.create_index(
        "comercio_usuarios_comercio_id_idx",
        "comercio_usuarios",
        ["comercio_id"],
    )


def downgrade() -> None:
    """Drop the Phase 4A membership table and remove the new columns."""
    op.drop_index(
        "comercio_usuarios_comercio_id_idx",
        table_name="comercio_usuarios",
    )
    op.drop_index(
        "comercio_usuarios_cuenta_usuario_id_idx",
        table_name="comercio_usuarios",
    )
    op.drop_table("comercio_usuarios")

    op.drop_constraint(
        "borrador_onboarding_comercio_comercio_id_completado_en_paired",
        _TABLE,
        type_="check",
    )
    op.drop_column(_TABLE, "completado_en")
    op.drop_constraint(
        "borrador_onboarding_comercio_comercio_id_unique",
        _TABLE,
        type_="unique",
    )
    op.drop_constraint(
        "borrador_onboarding_comercio_comercio_id_fkey",
        _TABLE,
        type_="foreignkey",
    )
    op.drop_column(_TABLE, "comercio_id")

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column("slug")
