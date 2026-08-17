"""add global medios_pago availability flags

Revision ID: f1g2h3i4j5k6
Revises: e1a2b3c4d5f6
Create Date: 2026-08-17 12:00:00.000000

The ``add-global-payment-field-configuration`` change introduces two
non-null Boolean flags on the global ``MediosPago`` catalog:

* ``habilita_titular`` — when ``True`` a future commerce-specific
  configuration form MAY permit the operator to edit the
  ``ComercioMedioPago.titular`` value for the resulting
  ``(comercio, medio_pago)`` association. The flag governs form
  availability only; it never makes the per-commerce value required.
* ``habilita_alias`` — same contract for ``ComercioMedioPago.alias``.

Both columns default to ``False`` at both the ORM and the database
levels so existing rows backfill safely and the safe "do not edit"
posture is the documented baseline.

The change is purely additive and intentionally narrow:

* ``ComercioMedioPago`` is untouched. The per-commerce values stay on
  the association, the global catalog never owns a concrete
  ``titular`` or ``alias`` value, and disabling a global flag does
  not clear or alter any existing per-commerce value.
* ``pedidos`` and the orders lineage are not touched.
* ``comercio_medios_pago`` rows are not backfilled or rewritten.
* The downgrade drops only the two added columns; the previous
  schema state is restored exactly without rewinding any other
  catalog column.

Upgrade contract:

1. ``ALTER TABLE medios_pago ADD COLUMN habilita_titular`` with a
   non-null Boolean column and an effective server default of
   ``false``. The server default ensures existing production rows
   acquire the safe ``false`` value at the moment the column is
   introduced; PostgreSQL then writes ``false`` for every row before
   the NOT NULL constraint is enforced.
2. Repeat for ``habilita_alias``.

Downgrade contract:

1. Drop ``habilita_alias``.
2. Drop ``habilita_titular``.

The migration never reads, writes, or rewrites
``comercio_medios_pago``, ``pedidos`` or any historical payment
value. The catalog stays the sole authority for the new flags.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1g2h3i4j5k6"
down_revision: str | Sequence[str] | None = "e1a2b3c4d5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "medios_pago",
        sa.Column(
            "habilita_titular",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "medios_pago",
        sa.Column(
            "habilita_alias",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("medios_pago", "habilita_alias")
    op.drop_column("medios_pago", "habilita_titular")