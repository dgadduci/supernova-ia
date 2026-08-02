# 3.30.3 Duplicate audit (pre-implementation inspection)

Inspection ran on 2026-07-31 via:

```sql
SELECT id, id_pedido, id_producto_presentacion, cantidad, precio_unitario, observaciones, created_at
FROM pedidos_productos
WHERE (id_pedido, id_producto_presentacion) IN (
    SELECT id_pedido, id_producto_presentacion
    FROM pedidos_productos
    GROUP BY id_pedido, id_producto_presentacion
    HAVING COUNT(*) > 1
)
ORDER BY id_pedido, id_producto_presentacion, id;
```

## supernova (production database)

No duplicate groups observed.

## supernova_test (development database)

Eight duplicate groups observed across `pedidos_productos`, totalling 20 rows that will be consolidated into 8 surviving rows by the new `uq_pedido_producto_presentacion` migration.

| id_pedido | id_producto_presentacion | duplicate rows (id) | summed cantidad | survivor id (lowest) | survivor precio_unitario | survivor observaciones |
|-----------|--------------------------|---------------------|-----------------|----------------------|--------------------------|------------------------|
| 2225 | 32 | 334, 335 | 2 | 334 | 5329.00 | NULL |
| 2352 | 1 | 374, 377, 382, 384, 385 | 5 | 374 | 20274.00 | NULL |
| 2352 | 4 | 379, 383 | 3 | 379 | 10274.00 | NULL |
| 2352 | 32 | 375, 378, 381 | 4 | 375 | 5329.00 | NULL |
| 2414 | 42 | 406, 407 | 2 | 406 | 7425.00 | NULL |
| 2470 | 36 | 474, 475 | 5 | 474 | 5877.00 | NULL |
| 2515 | 2 | 485, 487 | 4 | 485 | 10137.00 | NULL |
| 2515 | 36 | 484, 486 | 3 | 484 | 5877.00 | NULL |

## Strategy

The migration follows the documented deterministic consolidation strategy:

1. **Identify duplicates** via `GROUP BY ... HAVING COUNT(*) > 1`.
2. **For each group**: keep the lowest `id` as the survivor, sum the `cantidad` of every row into the survivor, preserve the lowest row's `precio_unitario` and `observaciones` (which is the survivor's because the survivor IS the lowest row), `DELETE` the other rows.
3. **Create** `uq_pedido_producto_presentacion` on `(id_pedido, id_producto_presentacion)`.

The consolidation is destructive and **not** reversed by `downgrade()` — the unique constraint is dropped, but the pre-consolidation row state is not restored (the migration is documented as a one-way consolidation).
