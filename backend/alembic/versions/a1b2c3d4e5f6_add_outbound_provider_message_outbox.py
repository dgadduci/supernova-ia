"""add outbound provider message outbox

Revision ID: a1b2c3d4e5f6
Revises: f7a3b8c1d2e4
Create Date: 2026-08-06 21:30:00.000000

Phase 5.6 introduces ``mensajes_proveedor_salientes`` as the durable,
provider-neutral work item for customer responses produced by a first
valid Phase-5.4 inbound receipt. The row stores the immutable canonical
destination, the rendered response body, the provider identity, the
inbound receipt foreign key, a zero-based ``sequence`` unique per
receipt, the dispatch state, lease token/expiry, attempt count,
next-attempt timestamp, the provider SID when accepted, the last safe
failure category/code and the provider-status timestamp. It never
stores Twilio credentials, signature values or raw provider callback
payloads.

The row is committed atomically alongside the inbound receipt, the
compatible session and the existing message pipeline in the same
Phase-5.4 transaction. A duplicate inbound receipt creates no new row;
a rollback leaves no durable outbox state. The
``(recepcion_mensaje_proveedor_id, sequence)`` unique constraint
guarantees that exactly one row per inbound response position is
durable so the response ordering is observable.

The migration adds the table, the unique constraint and the restrictive
foreign key to ``recepciones_mensajes_proveedor``. ``downgrade()`` drops
only this table; it does not rewrite any existing receipt row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f7a3b8c1d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mensajes_proveedor_salientes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proveedor", sa.String(length=32), nullable=False),
        sa.Column(
            "recepcion_mensaje_proveedor_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("destinatario_e164", sa.String(length=32), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "estado",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "identificador_proveedor", sa.String(length=128), nullable=True
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
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "codigo_ultimo_fallo", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "estado_proveedor", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "estado_proveedor_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "fecha_creacion",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "id", name="mensajes_proveedor_salientes_pkey"
        ),
        sa.UniqueConstraint(
            "recepcion_mensaje_proveedor_id",
            "sequence",
            name="mensajes_proveedor_salientes_recepcion_sequence_unico",
        ),
        sa.ForeignKeyConstraint(
            ["recepcion_mensaje_proveedor_id"],
            ["recepciones_mensajes_proveedor.id"],
            name="mensajes_proveedor_salientes_recepcion_fk",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_mensajes_proveedor_salientes_recepcion_id"),
        "mensajes_proveedor_salientes",
        ["recepcion_mensaje_proveedor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mensajes_proveedor_salientes_estado"),
        "mensajes_proveedor_salientes",
        ["estado"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mensajes_proveedor_salientes_proximo_intento_en"),
        "mensajes_proveedor_salientes",
        ["proximo_intento_en"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mensajes_proveedor_salientes_identificador_proveedor"),
        "mensajes_proveedor_salientes",
        ["identificador_proveedor"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mensajes_proveedor_salientes_identificador_proveedor"),
        table_name="mensajes_proveedor_salientes",
    )
    op.drop_index(
        op.f("ix_mensajes_proveedor_salientes_proximo_intento_en"),
        table_name="mensajes_proveedor_salientes",
    )
    op.drop_index(
        op.f("ix_mensajes_proveedor_salientes_estado"),
        table_name="mensajes_proveedor_salientes",
    )
    op.drop_index(
        op.f("ix_mensajes_proveedor_salientes_recepcion_id"),
        table_name="mensajes_proveedor_salientes",
    )
    op.drop_table("mensajes_proveedor_salientes")