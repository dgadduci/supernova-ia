## 1. Model and Migration

- [x] 1.1 Create `backend/models/pedido_producto.py` with the `PedidoProducto` model (`__tablename__ = "pedidos_productos"`). Include `id`, `id_pedido` (FK `CASCADE` → `pedidos.id`), `id_producto_presentacion` (FK `RESTRICT` → `producto_presentaciones.id`), `cantidad` (`Integer`, non-null, `CheckConstraint("cantidad > 0", name="cantidad_positiva")`), `precio_unitario` (`Numeric(12, 2)`, non-null), `observaciones` (`Text`, nullable), `created_at` (`DateTime(timezone=True)`, `server_default=func.now()`), `updated_at` (`DateTime(timezone=True)`, `server_default=func.now(), onupdate=func.now()`). Add `Mapped[Pedido]` and `Mapped[ProductoPresentacion]` relationship attributes. Do NOT add a reverse relationship on `Pedido`.
- [x] 1.2 Export `PedidoProducto` from `backend/models/__init__.py` next to the existing 16 model exports.
- [x] 1.3 Import `PedidoProducto` in `backend/alembic/env.py` next to the existing 15 model imports so autogenerate sees it.
- [x] 1.4 Generate the Alembic migration with `PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add pedidos_productos table"`. Confirm the new revision creates only the `pedidos_productos` table.
- [x] 1.5 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Repository and Service

- [x] 2.1 Create `backend/repositories/pedido_producto_repository.py` with `get`, `list_by_pedido`, `create`, `update`, and `delete` methods. Add a `pedido_in_borrador` and `producto_presentacion_exists` helper that the service uses. No commit/rollback in the repository.
- [x] 2.2 Create `backend/services/pedido_producto_service.py` that owns commit/rollback, the borrador-only guard, and the price-snapshot lookup. The `add` flow: validate pedido exists and is in `borrador` (else `PedidoNotFound` → 404 / `PedidoProductoNotEditable` → 409); validate producto-presentación exists (else `ProductoPresentacionNotFound` → 404); read the current `Precio` row for the producto-presentación (else `PrecioNotFound` → 400); persist with `precio_unitario` from that snapshot. The `update` flow: same borrador check on the parent pedido; reject `cantidad < 1`; trim `observaciones` (empty-after-trim → `None`).
- [x] 2.3 Extend `backend/services/exceptions.py` with `PedidoProductoNotFound` and `PedidoProductoNotEditable`. Reuse existing `PedidoNotFound`, `ProductoPresentacionNotFound`, and `PrecioNotFound`. (No need for a new `InvalidCantidad` because Pydantic's `Field(ge=1)` returns 422 at the schema layer.)

## 3. Schemas

- [x] 3.1 Create `backend/schemas/pedido_producto.py` with: `PedidoProductoCreate` (`id_producto_presentacion: int`, `cantidad: int = Field(ge=1)`, `observaciones: str | None`, `extra="forbid"`), `PedidoProductoUpdate` (`cantidad: int | None = Field(default=None, ge=1)`, `observaciones: str | None`, `extra="forbid"`), and `PedidoProductoResponse` (scalar fields including `precio_unitario` and `created_at` / `updated_at`, `from_attributes=True`).

## 4. Router

- [x] 4.1 Create `backend/routers/pedido_productos.py` with five endpoints: `POST /pedidos/{pedido_id}/productos`, `GET /pedidos/{pedido_id}/productos`, `GET /pedidos-productos/{item_id}`, `PUT /pedidos-productos/{item_id}`, `DELETE /pedidos-productos/{item_id}`. Translate `PedidoProductoNotFound` → 404, `PedidoProductoNotEditable` / `PedidoNotFound` → 404 or 409 per spec, `ProductoPresentacionNotFound` → 404, `PrecioNotFound` → 400.
- [x] 4.2 Register the new router in `backend/main.py`.

## 5. Verification

- [x] 5.1 Add integration tests under `backend/tests/` covering: successful creation snapshots the current `Precio`; `precio_unitario` field rejected (422); reject nonexistent pedido (404); reject nonexistent producto-presentación (404); reject producto-presentación without `Precio` (400); reject `cantidad < 1` (422); reject add when pedido is not in `borrador` (409); list-by-pedido returns line items; empty list when pedido has no items; get-by-id; update `cantidad` and `observaciones`; reject update with `precio_unitario` (422); reject update when pedido is not in `borrador` (409); delete succeeds in `borrador`; reject delete when pedido is not in `borrador` (409); missing item returns 404. Run against `supernova_test`.
- [x] 5.2 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, `venv/bin/ruff check backend`, and `venv/bin/mypy backend`. Report any pre-existing unrelated errors without changing unrelated files.