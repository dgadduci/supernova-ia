"""add deferred provider inbound processing work item

Revision ID: 7c4d5e6f7a8b
Revises: a1b2c3d4e5f6
Create Date: 2026-08-08 12:00:00.000000

Phase 7.4 introduces ``procesamientos_mensajes_proveedor`` as the
durable, lease-protected work item that records the deferred business
processing of one provider-message receipt. The webhook acceptance path
inserts exactly one pending row alongside the receipt; the bounded
operator CLI then leases, processes and finalizes the row through the
existing ``process_incoming_message`` pipeline and outbox mapper.

The work item is keyed one-to-one by the unique foreign key
``recepcion_mensaje_proveedor_id``: a second ``INSERT`` for an existing
receipt is blocked by the database so the deferred work can never
duplicate. The row carries the receipt relation, state, attempt count,
``proximo_intento_en``, lease token/expiry, safe failure
category/code, transient ``mensaje`` body and timestamps. The deferred
processor clears the body on successful processing or terminal
exhaustion so the row retains only safe state and metadata.

The work item never stores the customer destination (E.164) nor any
provider payload, signature or credential. The deferred processor
derives the destination outbound address from the still-authoritative
``cliente`` row referenced by the linked receipt; copying the address
onto the work item would let a stale work item target a number that no
longer belongs to this conversation.

The migration adds the table, the unique constraint and the
restrictive foreign key to ``recepciones_mensajes_proveedor``.
``downgrade()`` drops only this table; it does not rewrite any
existing receipt or outbox row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c4d5e6f7a8b"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "procesamientos_mensajes_proveedor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "recepcion_mensaje_proveedor_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "intentos",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "proximo_intento_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "token_lease", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "lease_expira_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "categoria_ultimo_fallo",
            sa.String(length=48),
            nullable=True,
        ),
        sa.Column(
            "codigo_ultimo_fallo", sa.String(length=48), nullable=True
        ),
        sa.Column("mensaje", sa.Text(), nullable=True),
        sa.Column(
            "fecha_creacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "fecha_finalizacion",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id", name="procesamientos_mensajes_proveedor_pkey"
        ),
        sa.UniqueConstraint(
            "recepcion_mensaje_proveedor_id",
            name=(
                "procesamientos_mensajes_proveedor_recepcion_unico"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["recepcion_mensaje_proveedor_id"],
            ["recepciones_mensajes_proveedor.id"],
            name=(
                "procesamientos_mensajes_proveedor_recepcion_fk"
            ),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_procesamientos_mensajes_proveedor_recepcion_id"),
        "procesamientos_mensajes_proveedor",
        ["recepcion_mensaje_proveedor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_procesamientos_mensajes_proveedor_estado"),
        "procesamientos_mensajes_proveedor",
        ["estado"],
        unique=False,
    )
    op.create_index(
        op.f("ix_procesamientos_mensajes_proveedor_proximo_intento_en"),
        "procesamientos_mensajes_proveedor",
        ["proximo_intento_en"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f(
            "ix_procesamientos_mensajes_proveedor_proximo_intento_en"
        ),
        table_name="procesamientos_mensajes_proveedor",
    )
    op.drop_index(
        op.f("ix_procesamientos_mensajes_proveedor_estado"),
        table_name="procesamientos_mensajes_proveedor",
    )
    op.drop_index(
        op.f("ix_procesamientos_mensajes_proveedor_recepcion_id"),
        table_name="procesamientos_mensajes_proveedor",
    )
    op.drop_table("procesamientos_mensajes_proveedor")