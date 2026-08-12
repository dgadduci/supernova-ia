"""add pedidos observaciones

Revision ID: b0c1d2e3f4a5
Revises: 7c4d5e6f7a8b
Create Date: 2026-08-12 16:00:00.000000

The set-draft-order-observation change persists a single free-text
general observation that belongs to the borrador pedido as a whole.
The field is independent of ``PedidoProducto.observaciones`` (which
keeps the existing product-level note contract) and is reachable only
through the active session's associated ``session.id_pedido``.

The migration adds a single nullable ``Text`` column
``pedidos.observaciones``. It performs no backfill, adds no default
or server default, adds no ``CheckConstraint`` and creates no
index. ``downgrade()`` drops only this column; it does not rewrite
any existing pedido row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "7c4d5e6f7a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column("observaciones", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pedidos", "observaciones")
