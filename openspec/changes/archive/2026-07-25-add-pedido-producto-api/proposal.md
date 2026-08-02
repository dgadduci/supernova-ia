## Why

A `pedido` is a header with no line items. The WhatsApp channel and the operator console both need to attach products to an order, and each line item must lock in its price at the moment it is added so later catalog price changes do not retroactively alter past orders. Without `pedidos_productos` the pedido cannot carry what was actually ordered.

## What Changes

- Add a `PedidoProducto` SQLAlchemy model mapping to a new `pedidos_productos` table.
- Add an Alembic migration that creates the `pedidos_productos` table on both `supernova` and `supernova_test`.
- Add five sync FastAPI endpoints for the line-item lifecycle (add, list, get, update, delete) under the established `Router → Service → Repository → Model` layering.
- The `precio_unitario` column is set by the service from the current `Precio` row for the supplied `id_producto_presentacion` — the request body SHALL NOT accept a client-supplied price. The snapshot is durable: future changes to the catalog `Precio` do not alter the line item.
- Enforce "only while pedido is in `borrador`": create, update, and delete on a line item of a pedido outside `borrador` return HTTP 409.
- Enforce `cantidad >= 1` at both the schema layer and the DB level.
- Add `Mapped[Pedido]` and `Mapped[ProductoPresentacion]` relationships on `PedidoProducto`. No reverse relationship needed on `Pedido` for the active subphase.

## Capabilities

### New Capabilities

- `pedido-producto-api`: REST endpoints for the line-item lifecycle — add, list (by pedido), get, update (quantity or observations), delete.

### Modified Capabilities

- None.

## Impact

- Adds `backend/models/pedido_producto.py`, `backend/alembic/versions/<rev>_add_pedidos_productos_table.py`, `backend/routers/pedido_productos.py`, `backend/schemas/pedido_producto.py`, `backend/repositories/pedido_producto_repository.py`, `backend/services/pedido_producto_service.py`.
- Extends `backend/services/exceptions.py` with `PedidoProductoNotFound`, `PedidoProductoNotEditable`, `InvalidCantidad`, and reuses existing `PedidoNotFound` / `ProductoPresentacionNotFound` / `PrecioNotFound`.
- Extends `backend/alembic/env.py` so autogenerate sees the new model.
- Extends `backend/main.py` (registers `pedido_productos.router`).
- Affects both `supernova` and `supernova_test` databases via the new migration.
- No model renames, no breaking changes to existing endpoints.