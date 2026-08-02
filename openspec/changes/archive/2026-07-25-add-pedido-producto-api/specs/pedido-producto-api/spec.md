## ADDED Requirements

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