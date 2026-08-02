"""add session context_type

Revision ID: 1f2e3d4c5b6a
Revises: 9c5b1d3e4f6a
Create Date: 2026-07-25 20:00:00.000000

Adds a `context_type` String(50) column to the `sessions` table. The column
stores a `ContextType` string value (e.g. `"product_selection"`) or NULL
when no context is currently active. Pre-existing rows remain NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, Sequence[str], None] = "9c5b1d3e4f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "context_type",
            sa.String(50),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "context_type")