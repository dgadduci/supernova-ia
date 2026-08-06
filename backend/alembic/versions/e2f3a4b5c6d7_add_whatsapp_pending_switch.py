"""add whatsapp pending switch target

Revision ID: e2f3a4b5c6d7
Revises: 6d9e0f1a2b3c
Create Date: 2026-08-06 18:00:00.000000

Phase 5.3 extends ``contextos_clientes_canales_whatsapp`` with one
nullable restrictive foreign key ``comercio_id_cambio_pendiente`` that
records a proposed switch target while the existing
``comercio_id_seleccionado`` remains the authoritative selection.

The target is staged only by an explicit ``request_switch`` call and is
consumed (moved to ``comercio_id_seleccionado`` or cleared) only by an
explicit ``confirm_switch`` / ``cancel_switch`` call. Stale or foreign
targets fail closed without changing selection, target or pending text.

The migration adds only the column, its restrictive foreign key and its
index. ``downgrade()`` drops only that column / index and does not
rewrite any existing selection, message or pending switch value
(``downgrade()`` runs while no rows may exist for ``5.3``, but the
column is nullable so dropping it loses no committed selection /
message data).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "6d9e0f1a2b3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contextos_clientes_canales_whatsapp",
        sa.Column(
            "comercio_id_cambio_pendiente",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "contextos_clientes_canales_whatsapp_cambio_pendiente_fk",
        "contextos_clientes_canales_whatsapp",
        "comercios",
        ["comercio_id_cambio_pendiente"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_contextos_clientes_canales_whatsapp_cambio_pendiente"),
        "contextos_clientes_canales_whatsapp",
        ["comercio_id_cambio_pendiente"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contextos_clientes_canales_whatsapp_cambio_pendiente"),
        table_name="contextos_clientes_canales_whatsapp",
    )
    op.drop_constraint(
        "contextos_clientes_canales_whatsapp_cambio_pendiente_fk",
        "contextos_clientes_canales_whatsapp",
        type_="foreignkey",
    )
    op.drop_column(
        "contextos_clientes_canales_whatsapp",
        "comercio_id_cambio_pendiente",
    )
