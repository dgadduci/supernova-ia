from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

from backend.config.settings import load_settings

revision: str = "a7c9e1f2b3d4"
down_revision: str | Sequence[str] | None = "f68b6651e8e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMBEDDING_DIMENSION = load_settings().embedding_dimension


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "producto_presentacion_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_producto_presentacion", sa.Integer(), nullable=False),
        sa.Column(
            "vector",
            VECTOR(EMBEDDING_DIMENSION),
            nullable=False,
        ),
        sa.Column("modelo", sa.String(length=150), nullable=False),
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
            ["id_producto_presentacion"],
            ["producto_presentaciones.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id_producto_presentacion",
            "modelo",
            name="producto_presentacion_embedding_unico",
        ),
    )
    op.create_index(
        "ix_producto_presentacion_embeddings_id_producto_presentacion",
        "producto_presentacion_embeddings",
        ["id_producto_presentacion"],
        unique=False,
    )
    op.create_index(
        "ix_producto_presentacion_embeddings_modelo",
        "producto_presentacion_embeddings",
        ["modelo"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_producto_presentacion_embeddings_modelo",
        table_name="producto_presentacion_embeddings",
    )
    op.drop_index(
        "ix_producto_presentacion_embeddings_id_producto_presentacion",
        table_name="producto_presentacion_embeddings",
    )
    op.drop_table("producto_presentacion_embeddings")
