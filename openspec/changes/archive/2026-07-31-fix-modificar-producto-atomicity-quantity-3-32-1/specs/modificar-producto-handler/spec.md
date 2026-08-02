# Capability: modificar-producto-handler

## Purpose

Provide the ready handler and the atomic service operation for `modificar_producto`. The handler validates intent shape, delegates the atomic mutation to `PedidoProductoService.modify_product`, and never mutates rows manually. The service enforces every business rule (draft Pedido, ownership, source validity, destination validity, quantity semantics, equivalent-modification guard, unique-line invariant, price-snapshot preservation) inside the existing transaction boundary, with strict validation-before-mutation semantics and authoritative quantity derivation that preserves the source-line quantity when the modification quantity is omitted.

## MODIFIED Requirements

### Requirement: Service pre-mutation validations

The service SHALL perform, in order, every required validation before any source row is mutated: Pedido exists; Pedido is in `borrador`; Session is active according to current rules; source `PedidoProducto` belongs to that Pedido; source quantity is positive; requested `cantidad` is positive when provided; requested `cantidad` does not exceed current source quantity; destination producto-presentación exists; destination belongs to the same comercio; destination is active and available; source and destination are not equivalent; destination price snapshot is available when a new destination line must be created; destination consolidation lookup has run.

#### Scenario: Pedido not in borrador is rejected

- **WHEN** the Pedido is not in `borrador` state
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="pedido_not_editable"` and the Pedido is unchanged

#### Scenario: Source line not in Pedido is rejected

- **WHEN** `pedido_producto_origen_id` does not belong to the supplied Pedido
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="source_not_in_pedido"` and the Pedido is unchanged

#### Scenario: Excess quantity is rejected

- **WHEN** `cantidad > source.cantidad`
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="quantity_exceeds_source"` and `resolved_data["cantidad_actual"] == source.cantidad`, and the Pedido is unchanged

#### Scenario: Destination not active is rejected

- **WHEN** the destination `ProductoPresentacion` is inactive or unavailable
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="destination_unavailable"` and the Pedido is unchanged

#### Scenario: Destination belongs to a different comercio is rejected

- **WHEN** the destination `ProductoPresentacion` belongs to a different comercio
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="destination_foreign_comercio"` and the Pedido is unchanged

#### Scenario: Validation order prohibits source mutation before destination validation

- **WHEN** `PedidoProductoService.modify_product` is invoked
- **THEN** the source row's `cantidad` and `id` are unchanged until every destination validation has returned successfully

### Requirement: Quantity semantics

The service SHALL compute `cantidad_a_modificar` exclusively from the explicit `cantidad` argument or the re-read current source-line quantity when `cantidad` is omitted. The service SHALL then apply the source update and destination update atomically inside the existing transaction boundary. The destination quantity SHALL always equal `cantidad_a_modificar` and SHALL NEVER default to `1`.

#### Scenario: Omitted cantidad modifies the full source line

- **WHEN** `cantidad is None` and the re-read source line has `cantidad == 4`
- **THEN** `cantidad_a_modificar == 4` and the source line is deleted (since `cantidad_a_modificar == source.cantidad`)

#### Scenario: Partial modification decrements source and increments destination

- **WHEN** `cantidad < source.cantidad`
- **THEN** the service decrements source by `cantidad` and creates or increments the destination line by `cantidad`, all in the same atomic operation

#### Scenario: Equal quantity deletes source and increments destination

- **WHEN** `cantidad == source.cantidad`
- **THEN** the service deletes the source line and creates or increments the destination line by `cantidad`, all in the same atomic operation

#### Scenario: Destination quantity never defaults to one

- **WHEN** `cantidad is None`
- **THEN** `cantidad_a_modificar` is derived from the re-read source quantity and never from the literal `1`

### Requirement: Atomic mutation semantics

The handler SHALL return `executed` only when the service reports a successful atomic mutation. The handler SHALL NOT decompose the mutation into separate source-decrement and destination-increment calls. The handler SHALL NOT call `execute_quitar_producto` or `execute_agregar_producto`. The handler SHALL return exactly one `ProcessedIntent` per modification message.

#### Scenario: Successful mutation returns executed

- **WHEN** the service completes the atomic mutation and returns a `ModificationResult` indicating success
- **THEN** `execute_modificar_producto` returns a copied `ProcessedIntent(status="executed", intent="modificar_producto")` with `resolved_data` enriched with `producto_origen_nombre`, `presentacion_origen`, `producto_destino_nombre`, `presentacion_destino`, `cantidad_modificada`, `cantidad_origen_restante`, `cantidad_destino_final`, `origen_eliminado`, `destino_creado`

#### Scenario: Service rejects return rejected without mutation

- **WHEN** the service returns `rejected` for an excess-quantity, source-absent, destination-unavailable, or equivalent-modification case
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected", intent="modificar_producto")` enriched with the deterministic rejection reason

#### Scenario: Handler never invokes quitar_producto or agregar_producto

- **WHEN** the handler source is inspected
- **THEN** it does not import `execute_quitar_producto` or `execute_agregar_producto`

#### Scenario: Handler returns exactly one ProcessedIntent

- **WHEN** `execute_modificar_producto(db, session, intent)` returns for any branch
- **THEN** the function returns exactly one `ProcessedIntent`

### Requirement: Source quantity re-read at execution time when omitted

When the resolved intent carries `cantidad is None`, the handler SHALL re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, immediately before invoking the service. The re-read value SHALL be passed to the service as the explicit transfer quantity. The handler SHALL NOT substitute `1` and SHALL NOT rely on a cached source quantity.

#### Scenario: Omitted quantity re-read uses current source quantity

- **WHEN** the source PedidoProducto currently has `cantidad == 4` and the resolved intent has `cantidad is None`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 4`, passes it to the service as the explicit quantity, and the destination receives `cantidad == 4`

#### Scenario: Source quantity changed since resolution is detected

- **WHEN** the source PedidoProducto currently has `cantidad == 3` even though the resolver previously persisted a different quantity
- **THEN** `execute_modificar_producto` re-reads `cantidad == 3` and passes it to the service; the destination receives `cantidad == 3`

### Requirement: No commit, rollback, or response generation in the handler

The handler SHALL NOT call `db.commit()`, `db.rollback()`, `db.flush()`, or generate a customer-facing response. Persistence and commit/rollback remain the caller's responsibility; response generation belongs to `build_modificar_producto_response`. The handler SHALL NOT decompose the mutation across multiple commits or transactional boundaries.

#### Scenario: Handler performs no commit or rollback

- **WHEN** `execute_modificar_producto(db, session, intent)` completes for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the handler module

#### Scenario: Handler does not import the response builder

- **WHEN** the handler module source is inspected
- **THEN** it does not import `build_modificar_producto_response` or any response-builder module

#### Scenario: No commit between source removal and destination addition

- **WHEN** the handler delegates to `PedidoProductoService.modify_product`
- **THEN** no commit, rollback, or flush has been issued between the source row mutation and the destination row mutation