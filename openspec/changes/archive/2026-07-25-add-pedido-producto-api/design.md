## Context

A `pedido` is currently a header with payment method, delivery method, scheduled time, and a state machine, but it has no list of what was ordered. Subphase 2.11 explicitly deferred line items ("No product-line items — the order is captured as a header only"). The catalog models — `Producto`, `ProductoPresentacion`, `Precio` — are in place from Phase 1 and Phase 2, and `Precio` is 1:1 with `ProductoPresentacion` via a unique index. This subphase introduces the line-item join, locking in the price at the moment of attachment.

## Goals / Non-Goals

**Goals:**

- Persist a `pedidos_productos` row with `id_pedido`, `id_producto_presentacion`, `cantidad`, `precio_unitario` (Decimal snapshot), and `observaciones` (nullable).
- Expose five sync FastAPI endpoints (add, list-by-pedido, get, update, delete) following the established layering.
- Apply a single Alembic migration to both `supernova` and `supernova_test`.
- Snapshot the price from the current `Precio` row at add time; the request body SHALL NOT accept a client-supplied price.
- Reject any add/update/delete on a line item of a pedido not in `borrador` with HTTP 409.
- Reject `cantidad < 1` at the schema layer (Pydantic `ge=1`) and at the DB level (CheckConstraint `cantidad_positiva`).
- Reject add when the supplied `id_producto_presentacion` has no `Precio` row (`PrecioNotFound` → 400).

**Non-Goals:**

- No reverse relationship on `Pedido` exposing the line-item list (the line-item endpoint is the entry point; the pedido response stays scalar).
- No total/aggregate computation (subtotal, tax, shipping) — out of scope; a future subphase will compute totals.
- No discount, promotion, or price override.
- No bulk add endpoint.
- No pagination or filtering (per pedido is naturally bounded).
- No reorder or line-item reordering endpoints.

## Decisions

- **D1 — `precio_unitario` is set by the service, never the client.** The Pydantic create schema accepts only `id_producto_presentacion`, `cantidad`, and `observaciones` (`extra="forbid"` rejects any `precio_unitario` field). The service reads the current `Precio` for the supplied `id_producto_presentacion` and copies its `precio` into the new `pedido_producto` row. The snapshot is durable: future changes to the catalog `Precio` do not alter existing line items.
- **D2 — Line item is read-only once pedido leaves `borrador`.** The service re-uses the same guard pattern as `pedido_service`: any write requires `pedido.estado_pedido == EstadoPedido.BORRADOR`. Read endpoints (list-by-pedido, get-by-id) do not require `borrador` — they always return the persisted line items.
- **D3 — `Numeric(12, 2)` for `precio_unitario` matches `Precio.precio`.** Same precision and scale; no extra conversion at the boundary. Pydantic schema exposes it as `Decimal`.
- **D4 — FK behavior.** `id_pedido` is `ON DELETE CASCADE` (a pedido owns its line items; deleting the pedido clears them — consistent with the `comercios` join pattern). `id_producto_presentacion` is `ON DELETE RESTRICT` (a catalog row cannot be deleted while any line item references it — consistent with the `producto_precios` pattern).
- **D5 — `cantidad` enforced at two layers.** Pydantic `Field(ge=1)` rejects 0 and negatives at the schema layer (returns 422). DB-level `CheckConstraint("cantidad > 0", name="cantidad_positiva")` is the source of truth.
- **D6 — `observaciones` is nullable free text.** `Text, nullable=True`. The service trims it; empty-after-trim becomes `None`. Maximum length is not capped in the active subphase (per spec, `Text` is unbounded).
- **D7 — Layering.** New files mirror the existing per-resource layout: `backend/routers/pedido_productos.py`, `backend/schemas/pedido_producto.py`, `backend/repositories/pedido_producto_repository.py`, `backend/services/pedido_producto_service.py`. The service owns commit/rollback, the price snapshot lookup, and the borrador-only guard. The router translates domain exceptions to HTTP errors.
- **D8 — Endpoints are nested under `/pedidos/{pedido_id}/productos`.** The single-item endpoints (`GET /productos/{item_id}`, `PUT`, `DELETE`) carry the line item id. The `pedido_id` is in the URL for add/list, not in the body, so the operator cannot accidentally attach a line item to the wrong pedido.
- **D9 — Migration is a single `alembic revision --autogenerate`.** The new model is added to `backend/alembic/env.py` next to the existing 15 model imports so autogenerate sees it; the revision creates the `pedidos_productos` table only.

## Risks / Trade-offs

- **[Risk] Autogenerate misses the new model.** → Mitigation: import `PedidoProducto` in `backend/alembic/env.py` next to the existing 15 model imports before running `alembic revision --autogenerate`.
- **[Risk] `Precio` row missing for the supplied `id_producto_presentacion` causes a hard failure.** → Mitigation: D1 — the service explicitly checks the `Precio` exists and raises `PrecioNotFound` → 400. Avoids `IntegrityError` from `NOT NULL` insert.
- **[Risk] Two line items for the same `(id_pedido, id_producto_presentacion)` pair produce a confusing UI.** → Acceptable for the active subphase: the operator can add the same product-presentation multiple times with different `observaciones` (e.g. "sin cebolla" vs "extra queso"). A future subphase may add uniqueness if the product model requires it.
- **[Trade-off] Update endpoint accepts only `cantidad` and `observaciones`.** → The endpoint name is `update_quantity_or_observations` per the spec. `id_producto_presentacion` is immutable on update (changing the product identity is out of scope; delete + re-add is the path).

## Open Questions

- None. The schema, endpoint surface, and rules are fixed by Subphase 2.14 in `project.md`.