"""consolidate pedido_productos duplicates

Revision ID: 8e0a1b2c3d4f
Revises: 1f2e3d4c5b6a
Create Date: 2026-07-31 18:00:00.000000

Subphase 3.30.3 - Consolidate duplicate PedidoProducto rows.

Pre-implementation inspection (recorded in ``backend/doc/3-30-3-duplicate-audit.md``):

* ``supernova`` (production): no duplicate ``(id_pedido, id_producto_presentacion)``
  groups were observed in ``pedidos_productos`` at the time of inspection.
* ``supernova_test`` (development): eight duplicate groups observed across
  twenty rows that this migration consolidates into eight surviving rows:

  =========== ======================= ============== =========== =============
  id_pedido   id_producto_presentacion duplicate ids summed cant. survivor id
  =========== ======================= ============== =========== =============
  2225        32                      334, 335       2           334
  2352        1                       374..385       5           374
  2352        4                       379, 383       3           379
  2352        32                      375, 378, 381  4           375
  2414        42                      406, 407       2           406
  2470        36                      474, 475       5           474
  2515        2                       485, 487       4           485
  2515        36                      484, 486       3           484
  =========== ======================= ============== =========== =============

Deterministic consolidation strategy
------------------------------------

For every duplicate ``(id_pedido, id_producto_presentacion)`` group:

1. The row with the lowest ``id`` is the survivor.
2. ``cantidad`` on the survivor is updated to the sum of every row in the
   group.
3. ``precio_unitario`` and ``observaciones`` on the survivor are preserved
   from the lowest row (which is the survivor itself, so no copy is
   required). All observed duplicate groups had identical ``precio_unitario``
   values and ``NULL`` ``observaciones`` at inspection time, so this rule is
   a strict no-op on existing data.

After consolidation, the ``uq_pedido_producto_presentacion`` unique
constraint is created on ``pedidos_productos (id_pedido, id_producto_presentacion)``
to enforce the "one line per product-presentation per pedido" invariant at
the database boundary.

The consolidation step is destructive and **not** reversible. ``downgrade()``
only drops the unique constraint; it does not attempt to restore the
pre-consolidation row state. Re-running ``upgrade()`` against an already
consolidated database is safe (the duplicate ``SELECT`` returns no rows)
but provides no data recovery if duplicates are re-introduced from an
out-of-band backup.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8e0a1b2c3d4f"
down_revision: Union[str, Sequence[str], None] = "1f2e3d4c5b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT id_pedido,
                   id_producto_presentacion,
                   array_agg(id ORDER BY id) AS ids,
                   SUM(cantidad) AS total_cantidad
            FROM pedidos_productos
            GROUP BY id_pedido, id_producto_presentacion
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for row in duplicate_rows:
        ids = list(row.ids)
        survivor_id = ids[0]
        total_cantidad = int(row.total_cantidad)
        bind.execute(
            sa.text(
                "UPDATE pedidos_productos SET cantidad = :cantidad WHERE id = :id"
            ),
            {"cantidad": total_cantidad, "id": survivor_id},
        )
        other_ids = ids[1:]
        if other_ids:
            bind.execute(
                sa.text("DELETE FROM pedidos_productos WHERE id = ANY(:ids)"),
                {"ids": other_ids},
            )

    op.create_unique_constraint(
        "uq_pedido_producto_presentacion",
        "pedidos_productos",
        ["id_pedido", "id_producto_presentacion"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_pedido_producto_presentacion",
        "pedidos_productos",
        type_="unique",
    )
