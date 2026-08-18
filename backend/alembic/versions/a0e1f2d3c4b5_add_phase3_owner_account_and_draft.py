"""add Phase 3 owner account and onboarding draft

Revision ID: a0e1f2d3c4b5
Revises: a1b2c3d4e5f7
Create Date: 2026-08-18 19:00:00.000000

The ``add-commerce-self-service-onboarding`` change introduces the
Phase 3 persistence boundary for the owner surface. Two narrow,
additive tables back the wizard:

* ``cuentas_usuario`` — application-owned mirror of the validated
  Supabase Auth subject. The row is keyed by an immutable external
  ``supabase_subject`` (``UNIQUE``) plus an internal surrogate
  ``id`` (``PRIMARY KEY``). The model carries an ``activo`` flag
  and audit timestamps only; it never stores email, profile
  metadata or any other provider field. The unique index is the
  durable cross-request resolution key, so the resolver never has
  to scan the table.

* ``borrador_onboarding_comercio`` — private per-account
  onboarding draft. The row references ``cuentas_usuario.id``
  with a unique constraint ``UNIQUE (cuenta_usuario_id)`` so the
  database itself enforces the "exactly one draft per account"
  contract regardless of how the application gets it wrong. The
  row carries a closed set of basic-commerce fields (legal name,
  WhatsApp number, address), plus a ``version`` counter used as
  the optimistic-concurrency token and a server-derived
  ``completo`` flag.

Upgrade contract:

1. Create ``cuentas_usuario`` with its primary key, unique external
   subject, ``activo`` flag, audit timestamps and optional
   ``fecha_baja``. No row is backfilled: Phase 2 did not persist
   identity, so there is nothing to migrate.
2. Create ``borrador_onboarding_comercio`` with its primary key,
   ``RESTRICT`` foreign key to ``cuentas_usuario.id``,
   ``UNIQUE (cuenta_usuario_id)`` constraint, ``version`` and
   ``completo`` counters (both default ``0`` / ``false``), the
   documented optional basic-commerce columns and audit
   timestamps.
3. None of ``comercios``, ``pedidos``, ``sessions``, ``clientes``,
   ``canales``, ``medios_pago``, ``metodos_entrega``,
   ``productos`` / catalogue, ``flavors_comunicacion`` or any
   association / lifecycle row is touched. The migration only
   adds tables; it never rewrites historical commerce / order
   data.

Downgrade contract:

1. Drop ``borrador_onboarding_comercio`` first so the foreign key
   to ``cuentas_usuario`` cannot block the second drop.
2. Drop ``cuentas_usuario``. The downgrade drops the tables only;
   no other schema state is reverted and no data is preserved (per
   the user-supplied Phase 3 scope).

Idempotency: every step uses straight ``op.create_table`` /
``op.drop_table`` calls. The migration is non-destructive: it
adds two tables without touching any pre-existing row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a0e1f2d3c4b5"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Phase 3 account and onboarding draft tables."""
    op.create_table(
        "cuentas_usuario",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "supabase_subject",
            sa.String(length=255),
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
        sa.UniqueConstraint(
            "supabase_subject",
            name="cuentas_usuario_supabase_subject_unique",
        ),
    )

    op.create_table(
        "borrador_onboarding_comercio",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "cuenta_usuario_id",
            sa.Integer(),
            sa.ForeignKey("cuentas_usuario.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "completo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("nombre_fantasia", sa.String(length=150), nullable=True),
        sa.Column("nombre_corto", sa.String(length=80), nullable=True),
        sa.Column("razon_social", sa.String(length=200), nullable=True),
        sa.Column("cuit", sa.String(length=20), nullable=True),
        sa.Column("whatsapp", sa.String(length=30), nullable=True),
        sa.Column("calle", sa.String(length=150), nullable=True),
        sa.Column("numero", sa.String(length=20), nullable=True),
        sa.Column(
            "piso_departamento", sa.String(length=50), nullable=True
        ),
        sa.Column("localidad", sa.String(length=100), nullable=True),
        sa.Column("provincia", sa.String(length=100), nullable=True),
        sa.Column("codigo_postal", sa.String(length=20), nullable=True),
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
        sa.UniqueConstraint(
            "cuenta_usuario_id",
            name="borrador_onboarding_comercio_cuenta_usuario_unique",
        ),
    )


def downgrade() -> None:
    """Drop the Phase 3 tables in foreign-key-safe order."""
    op.drop_table("borrador_onboarding_comercio")
    op.drop_table("cuentas_usuario")
