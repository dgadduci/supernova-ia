## ADDED Requirements

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