## ADDED Requirements

### Requirement: Retrieve pedido detail with human-readable line items

The system SHALL provide `GET /pedidos/{pedido_id}/detalle` that returns the pedido's scalar fields together with a `lineas` array describing its current line items. Each entry in `lineas` SHALL carry exactly three fields: `cantidad` (non-negative integer), `producto_nombre` (str), and `presentacion_descripcion` (str). The response SHALL NOT include any database identifier (`id`, `id_pedido`, `id_pedido_producto`, `id_producto_presentacion`, `id_producto`, `id_presentacion`, `id_comercio`, etc.), `precio_unitario`, `observaciones`, or any other field not listed here. The endpoint SHALL be read-only: it SHALL NOT call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; it SHALL NOT mutate the pedido or its line items. The endpoint SHALL return 404 when the `pedido_id` does not exist. The endpoint SHALL return 200 with an empty `lineas` array when the pedido exists but has no line items. Line items SHALL be returned in the order persisted by the database (ascending by `pedido_producto.id`). The `presentacion_descripcion` SHALL be the `descripcion` field of the joined `Presentacion` row; if the joined row is missing or its `descripcion` is empty, the response SHALL carry the literal string `—` (em dash, U+2014) instead.

#### Scenario: Existing pedido with line items returns scalars and ordered lineas

- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for a pedido that has at least one line item
- **THEN** the system returns 200 with the pedido's scalar fields (`id`, `id_session`, `id_medio_pago`, `id_metodo_entrega`, `datetime_entrega_programada`, `estado_pedido`, `fecha_alta`, `fecha_ultima_modificacion`) and a `lineas` array, in the persisted order, where each entry exposes only `cantidad`, `producto_nombre`, and `presentacion_descripcion`

#### Scenario: Missing pedido returns 404

- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` with a non-existent id
- **THEN** the system returns 404 and performs no mutation

#### Scenario: Empty pedido returns empty lineas

- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for a pedido that has no line items
- **THEN** the system returns 200 with the pedido's scalar fields and `lineas: []`

#### Scenario: Missing presentation description falls back to em dash

- **WHEN** a line item's joined `Presentacion.descripcion` is missing or empty
- **THEN** that entry's `presentacion_descripcion` is the literal string `—`

#### Scenario: Endpoint does not expose database identifiers

- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle` for any pedido
- **THEN** the response body contains no key that starts with `id_` (other than the pedido's top-level scalar identifiers carried over from `PedidoResponse`), no `precio_unitario`, and no `observaciones`

#### Scenario: Endpoint is read-only

- **WHEN** the operator calls `GET /pedidos/{pedido_id}/detalle`
- **THEN** the system does not call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; the pedido and its line items are unchanged in the database
