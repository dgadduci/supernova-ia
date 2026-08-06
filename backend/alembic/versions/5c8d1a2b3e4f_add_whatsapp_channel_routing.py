"""add whatsapp channel routing tables

Revision ID: 5c8d1a2b3e4f
Revises: b8d0e2f3a4c5
Create Date: 2026-08-06 16:00:00.000000

Phase 5.1 introduces two new tables that persist WhatsApp destination
channels independently of ``Comercio.whatsapp``:

* ``canales_whatsapp`` — provider-scoped canonical destination-number
  authority with ``dedicated`` / ``shared`` modes and a direct
  exclusive ``Comercio`` foreign key for dedicated channels.
* ``comercios_canales_compartidos`` — shared-channel membership and
  permanent historical routing-code reservation. The
  ``(canal_id, routing_code_normalizado)`` uniqueness has NO active
  predicate: a revoked code stays reserved for the full channel
  history so a stale link/QR cannot be reassigned to another commerce.

The migration is reversible: ``downgrade()`` drops the two new tables
and the indexes / enum created here. No existing row is rewritten.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "5c8d1a2b3e4f"
down_revision: str | Sequence[str] | None = "b8d0e2f3a4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    canal_mode = sa.Enum(
        "dedicated",
        "shared",
        name="canal_whatsapp_mode",
    )

    op.create_table(
        "canales_whatsapp",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("destination_e164", sa.String(length=32), nullable=False),
        sa.Column("mode", canal_mode, nullable=False),
        sa.Column("id_comercio_exclusivo", sa.Integer(), nullable=True),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "fecha_alta",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("fecha_baja", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider <> ''", name="canal_whatsapp_provider_no_vacio"),
        sa.CheckConstraint(
            "destination_e164 <> ''",
            name="canal_whatsapp_destination_no_vacio",
        ),
        sa.CheckConstraint(
            "destination_e164 NOT LIKE 'whatsapp:%'",
            name="canal_whatsapp_destination_no_prefijo",
        ),
        sa.CheckConstraint(
            "destination_e164 LIKE '+%'",
            name="canal_whatsapp_destination_e164",
        ),
        sa.CheckConstraint(
            (
                "(mode = 'dedicated' AND id_comercio_exclusivo IS NOT NULL) "
                "OR (mode = 'shared' AND id_comercio_exclusivo IS NULL)"
            ),
            name="canal_whatsapp_mode_comercio_exclusivo_chk",
        ),
        sa.ForeignKeyConstraint(
            ["id_comercio_exclusivo"],
            ["comercios.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX canales_whatsapp_provider_destino_unico "
        "ON canales_whatsapp (provider, destination_e164) "
        "WHERE activo = true"
    )
    op.create_index(
        op.f("ix_canales_whatsapp_id_comercio_exclusivo"),
        "canales_whatsapp",
        ["id_comercio_exclusivo"],
        unique=False,
    )
    op.create_index(
        op.f("ix_canales_whatsapp_activo"),
        "canales_whatsapp",
        ["activo"],
        unique=False,
    )

    op.create_table(
        "comercios_canales_compartidos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canal_id", sa.Integer(), nullable=False),
        sa.Column("comercio_id", sa.Integer(), nullable=False),
        sa.Column("routing_code", sa.String(length=80), nullable=False),
        sa.Column("routing_code_normalizado", sa.String(length=80), nullable=False),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "fecha_alta",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "routing_code <> ''",
            name="comercio_canal_compartido_routing_code_no_vacio",
        ),
        sa.CheckConstraint(
            "routing_code_normalizado <> ''",
            name=(
                "comercio_canal_compartido_routing_code_normalizado_no_vacio"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["canal_id"],
            ["canales_whatsapp.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["comercio_id"],
            ["comercios.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canal_id",
            "routing_code_normalizado",
            name="comercios_canales_compartidos_canal_code_unico",
        ),
    )
    op.create_index(
        op.f("ix_comercios_canales_compartidos_canal_id"),
        "comercios_canales_compartidos",
        ["canal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_comercios_canales_compartidos_comercio_id"),
        "comercios_canales_compartidos",
        ["comercio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_comercios_canales_compartidos_activo"),
        "comercios_canales_compartidos",
        ["activo"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_comercios_canales_compartidos_activo"),
        table_name="comercios_canales_compartidos",
    )
    op.drop_index(
        op.f("ix_comercios_canales_compartidos_comercio_id"),
        table_name="comercios_canales_compartidos",
    )
    op.drop_index(
        op.f("ix_comercios_canales_compartidos_canal_id"),
        table_name="comercios_canales_compartidos",
    )
    op.drop_table("comercios_canales_compartidos")

    op.drop_index(
        op.f("ix_canales_whatsapp_activo"),
        table_name="canales_whatsapp",
    )
    op.drop_index(
        op.f("ix_canales_whatsapp_id_comercio_exclusivo"),
        table_name="canales_whatsapp",
    )
    op.execute("DROP INDEX IF EXISTS canales_whatsapp_provider_destino_unico")
    op.drop_table("canales_whatsapp")

    sa.Enum(name="canal_whatsapp_mode").drop(op.get_bind(), checkfirst=True)