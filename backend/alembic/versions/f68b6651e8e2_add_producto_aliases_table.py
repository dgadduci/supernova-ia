"""add_producto_aliases_table

Revision ID: f68b6651e8e2
Revises: 8e0a1b2c3d4f
Create Date: 2026-08-02 22:39:09.349974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f68b6651e8e2'
down_revision: Union[str, Sequence[str], None] = '8e0a1b2c3d4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'producto_aliases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_producto', sa.Integer(), nullable=False),
        sa.Column('id_producto_presentacion', sa.Integer(), nullable=True),
        sa.Column('alias', sa.String(length=150), nullable=False),
        sa.Column('alias_normalizado', sa.String(length=150), nullable=False),
        sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column(
            'fecha_alta',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'fecha_ultima_modificacion',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "alias <> ''",
            name='producto_alias_alias_no_vacio',
        ),
        sa.CheckConstraint(
            "alias_normalizado <> ''",
            name='producto_alias_alias_normalizado_no_vacio',
        ),
        sa.ForeignKeyConstraint(
            ['id_producto'],
            ['productos.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['id_producto_presentacion'],
            ['producto_presentaciones.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_producto_aliases_id_producto'),
        'producto_aliases',
        ['id_producto'],
        unique=False,
    )
    op.create_index(
        op.f('ix_producto_aliases_id_producto_presentacion'),
        'producto_aliases',
        ['id_producto_presentacion'],
        unique=False,
    )
    op.create_index(
        op.f('ix_producto_aliases_alias_normalizado'),
        'producto_aliases',
        ['alias_normalizado'],
        unique=False,
    )
    op.create_index(
        op.f('ix_producto_aliases_activo'),
        'producto_aliases',
        ['activo'],
        unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX producto_alias_general_unique "
        "ON producto_aliases (id_producto, alias_normalizado) "
        "WHERE id_producto_presentacion IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX producto_alias_presentacion_unique "
        "ON producto_aliases (id_producto, id_producto_presentacion, alias_normalizado) "
        "WHERE id_producto_presentacion IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS producto_alias_presentacion_unique")
    op.execute("DROP INDEX IF EXISTS producto_alias_general_unique")
    op.drop_index(op.f('ix_producto_aliases_activo'), table_name='producto_aliases')
    op.drop_index(
        op.f('ix_producto_aliases_alias_normalizado'),
        table_name='producto_aliases',
    )
    op.drop_index(
        op.f('ix_producto_aliases_id_producto_presentacion'),
        table_name='producto_aliases',
    )
    op.drop_index(
        op.f('ix_producto_aliases_id_producto'),
        table_name='producto_aliases',
    )
    op.drop_table('producto_aliases')
