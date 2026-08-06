"""add provider message receipt table

Revision ID: f7a3b8c1d2e4
Revises: e2f3a4b5c6d7
Create Date: 2026-08-06 19:30:00.000000

Phase 5.4 introduces ``recepciones_mensajes_proveedor`` as the durable,
idempotent committed boundary that proves a provider has delivered one
message to this system. The table is the authoritative proof that a
provider message has been processed exactly once: the first valid claim
is committed atomically alongside the conversation session and existing
message pipeline in the same transaction, and a duplicate committed
receipt returns ``already_processed`` without re-invoking the pipeline.

The receipt is keyed by the unique pair ``(proveedor,
identificador_recepcion)`` so equivalent deliveries (including provider
retries that arrive after the first commit) collapse onto the same row.
No other field participates in the uniqueness boundary. Raw message text,
outbound delivery state, retry counters and response payloads belong to
later phases and are deliberately not persisted on this row.

The migration adds the table, the unique constraint and the three
restrictive foreign keys (``canal_id``, ``cliente_id``, ``comercio_id``).
``downgrade()`` drops only this table; it does not rewrite any existing
session, channel, client, commerce or receipt row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a3b8c1d2e4"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recepciones_mensajes_proveedor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proveedor", sa.String(length=32), nullable=False),
        sa.Column(
            "identificador_recepcion", sa.String(length=128), nullable=False
        ),
        sa.Column("canal_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("comercio_id", sa.Integer(), nullable=False),
        sa.Column(
            "fecha_recepcion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="recepciones_mensajes_proveedor_pkey"),
        sa.UniqueConstraint(
            "proveedor",
            "identificador_recepcion",
            name="recepciones_mensajes_proveedor_proveedor_recepcion_unico",
        ),
        sa.ForeignKeyConstraint(
            ["canal_id"],
            ["canales_whatsapp.id"],
            name="recepciones_mensajes_proveedor_canal_fk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_id"],
            ["clientes.id"],
            name="recepciones_mensajes_proveedor_cliente_fk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comercio_id"],
            ["comercios.id"],
            name="recepciones_mensajes_proveedor_comercio_fk",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_recepciones_mensajes_proveedor_canal_id"),
        "recepciones_mensajes_proveedor",
        ["canal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recepciones_mensajes_proveedor_cliente_id"),
        "recepciones_mensajes_proveedor",
        ["cliente_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recepciones_mensajes_proveedor_comercio_id"),
        "recepciones_mensajes_proveedor",
        ["comercio_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recepciones_mensajes_proveedor_comercio_id"),
        table_name="recepciones_mensajes_proveedor",
    )
    op.drop_index(
        op.f("ix_recepciones_mensajes_proveedor_cliente_id"),
        table_name="recepciones_mensajes_proveedor",
    )
    op.drop_index(
        op.f("ix_recepciones_mensajes_proveedor_canal_id"),
        table_name="recepciones_mensajes_proveedor",
    )
    op.drop_table("recepciones_mensajes_proveedor")
