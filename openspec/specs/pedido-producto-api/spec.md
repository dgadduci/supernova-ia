# Capability: pedido-producto-api

## Purpose

Define the HTTP layer over the `PedidoProducto` (line item) model, covering the full CRUD-like lifecycle of line items attached to a `Pedido` in `borrador`, with a durable price snapshot at insert time, so the order line-item surface can be driven through the same FastAPI conventions established in earlier API subphases.
## Requirements
### Requirement: Add product to pedido
The system SHALL provide `POST /pedidos/{pedido_id}/productos` that creates a new line item. The request body SHALL accept `id_producto_presentacion`, `cantidad`, and `observaciones` (nullable). The body SHALL NOT accept `precio_unitario`; the service SHALL set that field by reading the current `Precio` row for the supplied `id_producto_presentacion` at insert time. The endpoint SHALL reject the call when the pedido is not in `borrador` with HTTP 409, when the pedido does not exist with HTTP 404, when the producto-presentación does not exist with HTTP 404, when the producto-presentación has no `Precio` row with HTTP 400, and when `cantidad < 1` with HTTP 422.

#### Scenario: Successful creation snapshots the price
- **WHEN** the pedido is in `borrador`, the operator calls the endpoint with a valid `id_producto_presentacion`, `cantidad >= 1`, and optional `observaciones`
- **THEN** the system reads the current `Precio` for the producto-presentación, persists the line item with `precio_unitario` set to that snapshot, and returns the persisted row

#### Scenario: precio_unitario is rejected
- **WHEN** the operator calls the endpoint with a `precio_unitario` field in the body
- **THEN** the system returns 422 and the line item is not created

#### Scenario: Reject nonexistent pedido
- **WHEN** the operator calls the endpoint with a `pedido_id` that does not exist
- **THEN** the system returns 404 and no line item is created

#### Scenario: Reject nonexistent producto-presentación
- **WHEN** the operator calls the endpoint with an `id_producto_presentacion` that does not exist
- **THEN** the system returns 404 and no line item is created

#### Scenario: Reject producto-presentación without Precio
- **WHEN** the operator calls the endpoint with a valid `id_producto_presentacion` that has no `Precio` row
- **THEN** the system returns 400 and no line item is created

#### Scenario: Reject quantity less than 1
- **WHEN** the operator calls the endpoint with `cantidad < 1`
- **THEN** the system returns 422 and no line item is created

#### Scenario: Reject add when pedido is not in borrador
- **WHEN** the pedido is in any state other than `borrador` and the operator calls the endpoint
- **THEN** the system returns 409 and no line item is created

### Requirement: List products by pedido
The system SHALL provide `GET /pedidos/{pedido_id}/productos` that returns the list of line items for the supplied pedido. The endpoint SHALL return 404 when the pedido does not exist. The endpoint SHALL return an empty list when the pedido has no line items.

#### Scenario: Existing line items are returned
- **WHEN** the operator calls the endpoint for a pedido with line items
- **THEN** the system returns the line items in their persisted order

#### Scenario: Pedido with no line items returns empty list
- **WHEN** the operator calls the endpoint for a pedido that has no line items
- **THEN** the system returns 200 with an empty array

#### Scenario: Missing pedido returns 404
- **WHEN** the operator calls the endpoint with a `pedido_id` that does not exist
- **THEN** the system returns 404

### Requirement: Get line item by id
The system SHALL provide `GET /pedidos-productos/{item_id}` that returns a single line item's scalar fields. The endpoint SHALL return 404 when the id does not exist.

#### Scenario: Existing item is returned
- **WHEN** the operator calls the endpoint with an existing `item_id`
- **THEN** the system returns the line item's scalar fields including `precio_unitario` and `cantidad`

#### Scenario: Missing item returns 404
- **WHEN** the operator calls the endpoint with a non-existent `item_id`
- **THEN** the system returns 404

### Requirement: Update line item quantity or observations
The system SHALL provide `PUT /pedidos-productos/{item_id}` that updates `cantidad` and/or `observaciones`. The endpoint SHALL accept either or both fields; the field `id_pedido` and `id_producto_presentacion` are immutable. The endpoint SHALL reject the call when the parent pedido is not in `borrador` with HTTP 409, when the item does not exist with HTTP 404, and when `cantidad < 1` with HTTP 422.

#### Scenario: Update quantity persists
- **WHEN** the parent pedido is in `borrador` and the operator calls the endpoint with a new `cantidad >= 1`
- **THEN** the system updates the line item and returns the updated row

#### Scenario: Update observations persists
- **WHEN** the parent pedido is in `borrador` and the operator calls the endpoint with new `observaciones`
- **THEN** the system updates the line item and returns the updated row

#### Scenario: Reject quantity less than 1
- **WHEN** the operator calls the endpoint with `cantidad < 1`
- **THEN** the system returns 422 and the line item is unchanged

#### Scenario: Reject update when pedido is not in borrador
- **WHEN** the parent pedido is in any state other than `borrador` and the operator calls the endpoint
- **THEN** the system returns 409 and the line item is unchanged

#### Scenario: Reject precio_unitario in body
- **WHEN** the operator calls the endpoint with a `precio_unitario` field in the body
- **THEN** the system returns 422 and the line item is unchanged

#### Scenario: Missing item returns 404
- **WHEN** the operator calls the endpoint with a non-existent `item_id`
- **THEN** the system returns 404 and no line item is modified

### Requirement: Delete line item
The system SHALL provide `DELETE /pedidos-productos/{item_id}` that removes the line item. The endpoint SHALL reject the call when the parent pedido is not in `borrador` with HTTP 409. The endpoint SHALL return 404 when the item does not exist.

#### Scenario: Successful delete on borrador pedido
- **WHEN** the parent pedido is in `borrador` and the operator calls the endpoint
- **THEN** the system removes the line item and returns 204

#### Scenario: Reject delete when pedido is not in borrador
- **WHEN** the parent pedido is in any state other than `borrador` and the operator calls the endpoint
- **THEN** the system returns 409 and the line item is unchanged

#### Scenario: Missing item returns 404
- **WHEN** the operator calls the endpoint with a non-existent `item_id`
- **THEN** the system returns 404

### Requirement: precio_unitario is a durable snapshot
The `precio_unitario` column SHALL be set from the current `Precio.precio` at insert time and SHALL NOT change thereafter. Future updates to the catalog `Precio` row SHALL NOT alter existing line items.

#### Scenario: Snapshot is preserved on price update
- **WHEN** a line item exists and the operator updates the catalog `Precio` for the underlying producto-presentación
- **THEN** the line item's `precio_unitario` is unchanged

### Requirement: Cantidad is positive
The `cantidad` column SHALL be `> 0` at the database level. The Pydantic schema SHALL reject `cantidad < 1` with HTTP 422 before any persistence attempt.

#### Scenario: DB-level check rejects zero or negative
- **WHEN** the schema-layer validation is bypassed and a `cantidad` of 0 or less is written directly
- **THEN** the database `CheckConstraint cantidad_positiva` returns an integrity error and the service surfaces 422

### Requirement: At most one PedidoProducto per product-presentation per pedido

A single `Pedido` SHALL contain at most one `PedidoProducto` row for any given `id_producto_presentacion`. The `pedidos_productos` table SHALL enforce this invariant at the database level through a `UniqueConstraint("id_pedido", "id_producto_presentacion", name="uq_pedido_producto_presentacion")` declared in `PedidoProducto.__table_args__` and reflected in the Alembic migration that creates the same constraint name on the `pedidos_productos` table. Any database write that would create a second `PedidoProducto` row for the same `(id_pedido, id_producto_presentacion)` pair SHALL fail with an `IntegrityError`.

#### Scenario: Database rejects a duplicate insert

- **WHEN** the application (or any direct SQL writer) attempts to insert a second `PedidoProducto` row whose `(id_pedido, id_producto_presentacion)` matches an existing row in `pedidos_productos`
- **THEN** PostgreSQL raises an `IntegrityError` against the `uq_pedido_producto_presentacion` constraint and the insert is rejected

#### Scenario: Different pedidos with the same product-presentation are allowed

- **WHEN** the application inserts a `PedidoProducto` row whose `(id_pedido, id_producto_presentacion)` does NOT match any existing row in `pedidos_productos`
- **THEN** the insert succeeds and the new row is persisted

### Requirement: Service-level consolidation through add_or_increment

`PedidoProductoService` SHALL expose a method `add_or_increment(pedido_id: int, id_producto_presentacion: int, cantidad: int, observaciones: str | None) -> PedidoProducto` that enforces the "one row per product-presentation per pedido" invariant by looking up an existing row first and incrementing its `cantidad` when found, or by creating a new row that snapshots the current `Precio.precio` when no row exists. The method SHALL NOT commit, rollback, or close the database session, and SHALL flush only if existing service conventions require it.

#### Scenario: First addition creates one row

- **WHEN** a draft `Pedido` has no `PedidoProducto` rows for `id_producto_presentacion` and `add_or_increment` is invoked with `cantidad >= 1`
- **THEN** the service creates exactly one new `PedidoProducto` row with `cantidad` set to the supplied value, `precio_unitario` set to the current `Precio.precio` for that product-presentation, and the supplied `observaciones` (trimmed; empty-after-trim stored as `NULL`)

#### Scenario: Subsequent addition increments the existing row

- **WHEN** a draft `Pedido` already contains a `PedidoProducto` row for the same `id_producto_presentacion` and `add_or_increment` is invoked with `cantidad >= 1`
- **THEN** the service increments the existing row's `cantidad` by the supplied value, preserves the existing `precio_unitario` snapshot, preserves the existing `observaciones`, and returns the updated row

#### Scenario: Multiple identical additions keep one row

- **WHEN** `add_or_increment` is invoked repeatedly for the same `id_producto_presentacion` on the same draft `Pedido`
- **THEN** the service keeps exactly one `PedidoProducto` row whose `cantidad` equals the sum of every supplied `cantidad` value and whose `precio_unitario` matches the snapshot taken on the first addition

#### Scenario: Different presentations on the same pedido stay separate

- **WHEN** a draft `Pedido` contains one `PedidoProducto` row for `id_producto_presentacion == A` and `add_or_increment` is invoked for `id_producto_presentacion == B`
- **THEN** the service leaves the existing row for `A` untouched and creates a new row for `B`

#### Scenario: Same presentation in different pedidos stays separate

- **WHEN** two distinct `Pedido` rows in `borrador` each contain a `PedidoProducto` for the same `id_producto_presentacion` and `add_or_increment` is invoked for the second pedido
- **THEN** the service leaves the first pedido's row untouched and increments (or creates) the second pedido's row independently

#### Scenario: Invalid cantidad is rejected

- **WHEN** `add_or_increment` is invoked with `cantidad <= 0`
- **THEN** the service raises a domain exception (e.g. `InvalidCantidad`) without inserting or mutating any row

#### Scenario: Non-borrador pedido is rejected

- **WHEN** the pedido associated with `pedido_id` is in any state other than `borrador`
- **THEN** the service raises `PedidoProductoNotEditable` without inserting or mutating any row

#### Scenario: Missing pedido is rejected

- **WHEN** `pedido_id` does not correspond to an existing `Pedido`
- **THEN** the service raises `PedidoNotFound` without inserting or mutating any row

#### Scenario: Missing product-presentation is rejected

- **WHEN** `id_producto_presentacion` does not correspond to an existing `ProductoPresentacion`
- **THEN** the service raises `ProductoPresentacionNotFound` without inserting or mutating any row

#### Scenario: Missing current price is rejected

- **WHEN** the `ProductoPresentacion` identified by `id_producto_presentacion` has no `Precio` row
- **THEN** the service raises `PrecioNotFound` and creates no row (an increment against an existing line is rejected because no new snapshot is being taken)

### Requirement: Repository lookup for an existing line within a pedido

`PedidoProductoRepository` SHALL expose a method `get_by_pedido_and_producto_presentacion(pedido_id: int, id_producto_presentacion: int) -> PedidoProducto | None` that returns the unique `PedidoProducto` row whose `id_pedido` matches `pedido_id` and whose `id_producto_presentacion` matches `id_producto_presentacion`, or `None` when no such row exists. The method SHALL query only the bounded `(pedido_id, id_producto_presentacion)` pair, SHALL NOT load unrelated `PedidoProducto` rows, and SHALL use SQLAlchemy exclusively.

#### Scenario: Lookup returns the matching row

- **WHEN** `get_by_pedido_and_producto_presentacion` is invoked for a `(pedido_id, id_producto_presentacion)` pair that matches a persisted `PedidoProducto`
- **THEN** the repository returns that row without loading unrelated line items

#### Scenario: Lookup returns None when no row matches

- **WHEN** `get_by_pedido_and_producto_presentacion` is invoked for a `(pedido_id, id_producto_presentacion)` pair that does NOT match any persisted `PedidoProducto`
- **THEN** the repository returns `None`

#### Scenario: Lookup does not return a row from a different pedido

- **WHEN** a `PedidoProducto` row exists with the same `id_producto_presentacion` but a different `id_pedido`
- **THEN** `get_by_pedido_and_producto_presentacion` returns `None` for the requested `pedido_id`

