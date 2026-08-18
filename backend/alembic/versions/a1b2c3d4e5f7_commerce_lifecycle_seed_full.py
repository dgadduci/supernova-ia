"""seed the full canonical commerce lifecycle states

Revision ID: a1b2c3d4e5f7
Revises: 9c5b1d3e4f6c
Create Date: 2026-08-17 19:30:00.000000

The ``9c5b1d3e4f6c_commerce_lifecycle_policy`` revision introduced the
typed ``estado_comercio.codigo`` / ``descripcion`` / ``modo_operacion``
/ ``seleccionable`` columns and backfilled every row that already
existed from its previous free-text ``estado`` label. The follow-up
did not insert the missing canonical rows, so production ended up
with only ``ACTIVO`` available in the panel even though the policy
contract exposes three selectable lifecycle states.

This revision is the narrowest possible fix:

* It is data-only — no schema changes, no new constraints, no
  catalog CRUD surface.
* It upserts the five canonical lifecycle states
  (``ACTIVO``, ``INACTIVO``, ``PRUEBA``, ``SUSPENDIDO``, ``BAJA``).
  Existing rows keep their ``id`` and every ``Comercio.estado_id``
  reference; only ``descripcion``, ``modo_operacion`` and
  ``seleccionable`` are touched.
* It is idempotent: re-running ``upgrade`` does not duplicate rows
  because the operation is keyed by ``codigo`` via
  ``ON CONFLICT (codigo) DO UPDATE``.
* It does not touch ``comercios``, ``pedidos``, ``sessions``,
  ``canales``, ``catalogo`` or any association row.
* The downgrade deletes only the rows this revision inserted.
  Pre-existing codigos are captured in a small helper table during
  the upgrade and used as a negative filter in the downgrade; any
  unrelated row created manually between upgrade and downgrade is
  left untouched.

A short-lived helper table (``estado_comercio_seed_pre_existing``)
records every ``codigo`` present before the upsert so the downgrade
can be precise. The helper table is created in ``upgrade`` and
dropped in ``downgrade``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "9c5b1d3e4f6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (codigo, descripcion, modo_operacion, seleccionable)
_CANONICAL: list[tuple[str, str, str, bool]] = [
    ("ACTIVO", "Activo", "habilitado", True),
    ("INACTIVO", "Inactivo", "bloqueado", True),
    ("PRUEBA", "Prueba", "prueba", True),
    ("SUSPENDIDO", "Suspendido", "bloqueado", False),
    ("BAJA", "Baja", "bloqueado", False),
]

_PRE_EXISTING_TABLE = "estado_comercio_seed_pre_existing"


def upgrade() -> None:
    """Upsert the five canonical lifecycle states idempotently."""
    bind = op.get_bind()

    op.execute(
        "CREATE TABLE "
        f"{_PRE_EXISTING_TABLE} ("
        " codigo VARCHAR(50) PRIMARY KEY,"
        " captured_at TIMESTAMP NOT NULL DEFAULT now()"
        ")"
    )
    op.execute(
        f"INSERT INTO {_PRE_EXISTING_TABLE} (codigo) "
        "SELECT codigo FROM estado_comercio"
    )

    for codigo, descripcion, modo, seleccionable in _CANONICAL:
        bind.execute(
            sa.text(
                "INSERT INTO estado_comercio "
                "(codigo, descripcion, modo_operacion, seleccionable) "
                "VALUES (:codigo, :descripcion, "
                "CAST(:modo AS estado_comercio_modo_operacion), "
                ":seleccionable) "
                "ON CONFLICT (codigo) DO UPDATE SET "
                "descripcion = EXCLUDED.descripcion, "
                "modo_operacion = EXCLUDED.modo_operacion, "
                "seleccionable = EXCLUDED.seleccionable"
            ),
            {
                "codigo": codigo,
                "descripcion": descripcion,
                "modo": modo,
                "seleccionable": seleccionable,
            },
        )


def downgrade() -> None:
    """Remove only the rows this revision inserted.

    The helper table records every ``codigo`` present before the
    upgrade. The downgrade deletes canonical rows whose ``codigo``
    was not present pre-upgrade; any unrelated row created manually
    between upgrade and downgrade is preserved.
    """
    op.execute(
        "DELETE FROM estado_comercio "
        "WHERE codigo IN ('ACTIVO', 'INACTIVO', 'PRUEBA', "
        "                  'SUSPENDIDO', 'BAJA') "
        f"AND codigo NOT IN (SELECT codigo FROM {_PRE_EXISTING_TABLE})"
    )
    op.execute(f"DROP TABLE {_PRE_EXISTING_TABLE}")