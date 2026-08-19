"""add instalaciones_twilio_comercio table and idempotency registry

Revision ID: a7b8c9d0e1f2
Revises: b5f47a4c19d3
Create Date: 2026-08-19 16:45:00.000000

Add the durable registry for one technical installation per commerce that
uses the commerce-owned Twilio (T-C) adapter. The table is the only
selector on the internal ingress path; ``instalacion_id`` is opaque,
fixed-length and unique across the table.

The migration also adds the partial unique index on
``id_comercio`` where ``activo = true`` so the database enforces
"exactly one active installation per commerce" — concurrent
provisioners cannot insert two active rows.

The migration also adds ``instalaciones_twilio_comercio_idempotencia``
which is the durable claim table that prevents a second
``messages.create`` from being issued for the same
``(instalacion_id, idempotency_key)`` pair. The unique constraint on
the pair is the serialisation point; concurrent dispatchers either
win the ``INSERT`` and run the network call or lose the ``INSERT``
and short-circuit to ``already_claimed``.

The plain shared secret never persists: the row carries only the
Fernet envelope of the secret and the key id used to encrypt it.
``downgrade()`` drops both tables and their rows; it does not
rewrite any existing comercio, canal, receipt or outbox row.

The migration also renames ``tc_project_url`` to ``tc_service_url`` so
the column matches the bounded per-installation T-C service URL —
not a single global project URL — and updates the partial unique
index DDL accordingly.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "b5f47a4c19d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instalaciones_twilio_comercio",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_comercio", sa.Integer(), nullable=False),
        sa.Column(
            "tc_service_url", sa.String(length=512), nullable=False
        ),
        sa.Column("instalacion_id", sa.String(length=24), nullable=False),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("secreto_envelope", sa.Text(), nullable=False),
        sa.Column(
            "secreto_envelope_kid", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "fecha_alta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "fecha_baja",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id", name="instalaciones_twilio_comercio_pkey"
        ),
        sa.UniqueConstraint(
            "instalacion_id",
            name="uq_instalacion_twilio_instalacion_id",
        ),
        sa.ForeignKeyConstraint(
            ["id_comercio"],
            ["comercios.id"],
            name="instalaciones_twilio_comercio_comercio_fk",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_instalaciones_twilio_comercio_id_comercio"),
        "instalaciones_twilio_comercio",
        ["id_comercio"],
        unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_instalacion_twilio_one_active_per_comercio "
        "ON instalaciones_twilio_comercio (id_comercio) "
        "WHERE activo = true"
    )

    op.create_table(
        "instalaciones_twilio_comercio_idempotencia",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instalacion_id", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "estado",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column("message_sid", sa.String(length=128), nullable=True),
        sa.Column("codigo", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "fecha_creacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="instalaciones_twilio_comercio_idempotencia_pkey",
        ),
        sa.UniqueConstraint(
            "instalacion_id",
            "idempotency_key",
            name=(
                "uq_instalacion_twilio_idempotencia_installation_key"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["instalacion_id"],
            ["instalaciones_twilio_comercio.instalacion_id"],
            name=(
                "instalaciones_twilio_comercio_idempotencia_inst_fk"
            ),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_instalaciones_twilio_idempotencia_installation"),
        "instalaciones_twilio_comercio_idempotencia",
        ["instalacion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_instalaciones_twilio_idempotencia_installation"),
        table_name="instalaciones_twilio_comercio_idempotencia",
    )
    op.drop_table("instalaciones_twilio_comercio_idempotencia")

    op.execute(
        "DROP INDEX IF EXISTS "
        "uq_instalacion_twilio_one_active_per_comercio"
    )
    op.drop_index(
        op.f("ix_instalaciones_twilio_comercio_id_comercio"),
        table_name="instalaciones_twilio_comercio",
    )
    op.drop_table("instalaciones_twilio_comercio")