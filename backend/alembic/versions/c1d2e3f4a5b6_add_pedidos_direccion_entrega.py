"""add pedidos direccion_entrega

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-08-12 20:30:00.000000

The ``set-draft-order-delivery-address`` change persists a single free-text
concrete delivery address that belongs to the ``borrador`` pedido as a
whole. The field is independent of ``Pedido.observaciones`` (which keeps
the existing general observation contract) and of
``PedidoProducto.observaciones`` (which remains the product-level note
contract). It is reachable only through the active session's associated
``session.id_pedido`` and is replaced, never parsed.

The migration adds a single nullable ``Text`` column
``pedidos.direccion_entrega``. It performs no backfill, adds no default
or server default, adds no ``CheckConstraint`` and creates no index.
``downgrade()`` drops only this column; it does not rewrite any existing
pedido row.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column("direccion_entrega", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pedidos", "direccion_entrega")