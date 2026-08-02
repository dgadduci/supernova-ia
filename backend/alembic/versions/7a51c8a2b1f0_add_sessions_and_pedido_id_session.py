"""add sessions and pedido id_session

Revision ID: 7a51c8a2b1f0
Revises: 4fe39cdd1c78
Create Date: 2026-07-25 18:30:00.000000

Creates the `sessions` table, adds the partial unique index for active
sessions per (comercio, cliente), and adds a non-null `id_session` FK to
the existing `pedidos` table. The circular FK between `sessions.id_pedido`
and `pedidos.id_session` is resolved in three phases:

  1. create sessions (without id_pedido FK yet)
  2. add id_session to pedidos as NULLABLE
  3. truncate any pre-existing pedidos rows (dev/test only — this project
     has no production data), then alter id_session to NOT NULL
  4. add the sessions.id_pedido FK via ALTER TABLE now that both sides
     exist
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a51c8a2b1f0"
down_revision: Union[str, Sequence[str], None] = "4fe39cdd1c78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_comercio", sa.Integer(), nullable=False),
        sa.Column("id_cliente", sa.Integer(), nullable=False),
        sa.Column("id_pedido", sa.Integer(), nullable=True),
        sa.Column("datetime_inicio", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("datetime_ultimo_movimiento", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "estado_session",
            sa.Enum("activa", "cerrada", name="estado_session"),
            server_default="activa",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["id_cliente"], ["clientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["id_comercio"], ["comercios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_session_activa_comercio_cliente",
        "sessions",
        ["id_comercio", "id_cliente"],
        unique=True,
        postgresql_where=sa.text("estado_session = 'activa'"),
    )

    op.add_column(
        "pedidos",
        sa.Column("id_session", sa.Integer(), nullable=True),
    )
    op.create_index(op.f("ix_pedidos_id_session"), "pedidos", ["id_session"])

    op.execute("TRUNCATE TABLE pedidos")

    op.alter_column("pedidos", "id_session", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "fk_pedidos_id_session",
        "pedidos",
        "sessions",
        ["id_session"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_foreign_key(
        "fk_sessions_id_pedido",
        "sessions",
        "pedidos",
        ["id_pedido"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_id_pedido", "sessions", type_="foreignkey")
    op.drop_constraint("fk_pedidos_id_session", "pedidos", type_="foreignkey")
    op.drop_index(op.f("ix_pedidos_id_session"), table_name="pedidos")
    op.drop_column("pedidos", "id_session")
    op.drop_index("uq_session_activa_comercio_cliente", table_name="sessions")
    op.drop_table("sessions")