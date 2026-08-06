"""add whatsapp shared routing context table

Revision ID: 6d9e0f1a2b3c
Revises: 5c8d1a2b3e4f
Create Date: 2026-08-06 14:00:00.000000

Phase 5.2 introduces ``contextos_clientes_canales_whatsapp`` to persist
the durable pre-commerce state of an existing client activating a
shared-channel membership. The table is intentionally independent of
``Session`` and records:

* the WhatsApp channel scope (``canal_id``);
* the existing client (``cliente_id``);
* the commerce selected from the active shared membership
  (``comercio_id_seleccionado``), nullable while activation is in
  flight;
* the caller-supplied raw original inbound text
  (``mensaje_original_pendiente``), preserved byte-for-byte so a later
  phase can route it through the business pipeline.

The ``(canal_id, cliente_id)`` unique constraint is unconditional: at
most one routing context exists per (channel, client) pair.

The migration is reversible: ``downgrade()`` drops the new table and
its index. No existing row is rewritten.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6d9e0f1a2b3c"
down_revision: str | Sequence[str] | None = "5c8d1a2b3e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contextos_clientes_canales_whatsapp",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canal_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("comercio_id_seleccionado", sa.Integer(), nullable=True),
        sa.Column("mensaje_original_pendiente", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["canal_id"],
            ["canales_whatsapp.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_id"],
            ["clientes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comercio_id_seleccionado"],
            ["comercios.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canal_id",
            "cliente_id",
            name="contextos_clientes_canales_whatsapp_canal_cliente_unico",
        ),
    )


def downgrade() -> None:
    op.drop_table("contextos_clientes_canales_whatsapp")
