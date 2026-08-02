"""convert session pending_intents to JSON

Revision ID: 9c5b1d3e4f6a
Revises: 8d4f6e2a9b1c
Create Date: 2026-07-25 19:30:00.000000

Alters `sessions.pending_intents` from TEXT (JSON-string) to JSONB so the
column stores a real JSON value rather than a JSON-encoded string. The Python
attribute becomes a dict; Pydantic `model_dump(mode="json")` and
`model_validate(...)` operate on dicts.

This migration is dev/test-only friendly: pre-existing rows are forced to
`{}` via a backfill before the type alteration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c5b1d3e4f6a"
down_revision: Union[str, Sequence[str], None] = "8d4f6e2a9b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE sessions SET pending_intents = '{}' WHERE pending_intents IS NULL")
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.Text(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.Text(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using="pending_intents::jsonb",
    )
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.JSON(),
        nullable=True,
        server_default=sa.text("'{}'::json"),
    )


def downgrade() -> None:
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.JSON(),
        server_default=None,
        nullable=True,
    )
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.JSON(),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="pending_intents::text",
    )
    op.alter_column(
        "sessions",
        "pending_intents",
        existing_type=sa.Text(),
        nullable=True,
        server_default=sa.text("'{}'"),
    )