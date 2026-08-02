"""add pedidos_productos table

Revision ID: 5803d45fe1e9
Revises: 7a51c8a2b1f0
Create Date: 2026-07-25 17:43:28.546277

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5803d45fe1e9'
down_revision: Union[str, Sequence[str], None] = '7a51c8a2b1f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pedidos_productos',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('id_pedido', sa.Integer(), nullable=False),
    sa.Column('id_producto_presentacion', sa.Integer(), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('precio_unitario', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('observaciones', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('cantidad > 0', name='cantidad_positiva'),
    sa.ForeignKeyConstraint(['id_pedido'], ['pedidos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_producto_presentacion'], ['producto_presentaciones.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pedidos_productos_id_pedido'), 'pedidos_productos', ['id_pedido'], unique=False)
    op.create_index(op.f('ix_pedidos_productos_id_producto_presentacion'), 'pedidos_productos', ['id_producto_presentacion'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_pedidos_productos_id_producto_presentacion'), table_name='pedidos_productos')
    op.drop_index(op.f('ix_pedidos_productos_id_pedido'), table_name='pedidos_productos')
    op.drop_table('pedidos_productos')
