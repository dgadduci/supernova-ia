"""make commerce communication flavor optional

Revision ID: e1a2b3c4d5f6
Revises: d1d2e3f4a5b6
Create Date: 2026-08-17 00:00:00.000000

The Phase-1 migration ``d1d2e3f4a5b6`` backfilled every existing
comercio with the canonical ``neutro`` flavor and made
``comercios.flavor_comunicacion_id`` ``NOT NULL``. This change
reverses the sentinel role of ``neutro``: commerce communication
flavor is now optional, and ``flavor_comunicacion_id = NULL`` is
the canonical no-op (deterministic outbound, zero LLM call).

Upgrade contract:

1. Resolve the global row whose ``codigo = 'neutro'`` if it
   exists. The lookup matches only on ``codigo`` and ignores the
   ``activo`` flag, so an inactive ``neutro`` row is still
   recognized as the canonical sentinel and its assignments are
   converted to ``NULL``. If the row is missing, the upgrade
   proceeds safely: no assignment is converted and no numeric ID
   is fabricated.
2. For every comercio whose ``flavor_comunicacion_id`` matches
   the resolved ``neutro`` row, set the column to ``NULL``.
   Non-neutral assignments are preserved exactly.
3. Make the foreign-key column nullable while preserving its
   foreign key and its supporting index.

Downgrade contract:

1. Resolve the global row whose ``codigo = 'neutro'``. The
   lookup matches only on ``codigo`` (inactive rows are
   acceptable). When the row is missing, the downgrade aborts
   with a typed failure before any mutation, rather than
   fabricating a numeric ID.
2. When the resolved row exists, use its ID to replace every
   ``NULL`` in ``comercios.flavor_comunicacion_id`` so the
   upcoming ``NOT NULL`` restoration cannot violate the
   constraint.
3. Restore the ``NOT NULL`` constraint, preserving the existing
   foreign key and index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: str | Sequence[str] | None = "d1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEUTRO_CODIGO = "neutro"


def _neutro_id(bind: sa.engine.Connection) -> int | None:
    """Resolve the canonical ``neutro`` flavor row by code.

    Returns the primary key when any row with that ``codigo``
    exists (active or inactive); returns ``None`` only when the
    row is missing. Callers must treat ``None`` as "no candidate
    to convert" rather than as "use a fabricated numeric ID".
    """
    row = bind.execute(
        sa.text(
            "SELECT id FROM flavors_comunicacion "
            "WHERE codigo = :codigo"
        ),
        {"codigo": NEUTRO_CODIGO},
    ).first()
    if row is None:
        return None
    return int(row[0])


def upgrade() -> None:
    bind = op.get_bind()
    op.alter_column(
        "comercios",
        "flavor_comunicacion_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    neutro_id = _neutro_id(bind)
    if neutro_id is not None:
        bind.execute(
            sa.text(
                "UPDATE comercios SET flavor_comunicacion_id = NULL "
                "WHERE flavor_comunicacion_id = :neutro_id"
            ),
            {"neutro_id": neutro_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    neutro_id = _neutro_id(bind)
    if neutro_id is None:
        raise RuntimeError(
            "Cannot downgrade: the canonical 'neutro' flavor row "
            "is missing. Restore it with codigo='neutro' (the "
            "activo flag is not required for the downgrade to "
            "use it) before retrying the downgrade."
        )

    bind.execute(
        sa.text(
            "UPDATE comercios SET flavor_comunicacion_id = :neutro_id "
            "WHERE flavor_comunicacion_id IS NULL"
        ),
        {"neutro_id": neutro_id},
    )

    op.alter_column(
        "comercios",
        "flavor_comunicacion_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
