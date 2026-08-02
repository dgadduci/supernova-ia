"""add session pending_intents

Revision ID: 8d4f6e2a9b1c
Revises: 5803d45fe1e9
Create Date: 2026-07-25 19:00:00.000000

Adds a `pending_intents` JSON-compatible Text column to the `sessions` table.
The column is nullable with a server default of `"{}"`. The active subphase
keeps it nullable; a future subphase may add a NOT NULL constraint once the
persistence surface is mature.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d4f6e2a9b1c"
down_revision: Union[str, Sequence[str], None] = "5803d45fe1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "pending_intents",
            sa.Text(),
            nullable=True,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "pending_intents")