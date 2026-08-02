# Capability: quitar-producto-handler

Provide the business-action handler that consumes ready `quitar_producto` intents, validates the resolved `pedido_producto_id` and optional `cantidad`, decrements or deletes the matching `PedidoProducto` row through the existing `PedidoProductoService`, and translates outcomes into `executed`, `rejected`, or `failed` statuses without owning database access, HTTP responses, context cleanup, or queue promotion.

## ADDED Requirements

### Requirement: Quitar producto handler module location

The system SHALL expose `execute_quitar_producto` from `backend/intents/handlers/quitar_producto_handler.py`.

#### Scenario: Handler is importable
- **WHEN** a module executes `from backend.intents.handlers.quitar_producto_handler import execute_quitar_producto`
- **THEN** the import succeeds and the binding is callable

### Requirement: Ready intent validation

The handler SHALL accept execution only when `intent.intent == "quitar_producto"`, `intent.status == "ready"`, `intent.handler == "quitar_producto"`, and `resolved_data` contains `pedido_producto_id`.

#### Scenario: Non-ready or wrong intent is rejected
- **WHEN** the handler receives an intent with an invalid intent name, handler name, status, or missing `pedido_producto_id`
- **THEN** it returns a new intent with `status == "rejected"` without mutating the pedido

### Requirement: Resolved value validation

The handler SHALL require an integer `pedido_producto_id` and, when present, an integer `cantidad` greater than zero. Invalid values SHALL return a `rejected` intent preserving the original intent fields.

#### Scenario: Invalid quantity is rejected
- **WHEN** `cantidad` is present but not an integer, less than one, or equal to zero
- **THEN** the handler returns `status == "rejected"` without invoking the service

#### Scenario: Invalid pedido_producto_id is rejected
- **WHEN** `pedido_producto_id` is missing or not an integer
- **THEN** the handler returns `status == "rejected"` preserving resolved data and requirements

### Requirement: Pedido and order-line ownership

The handler SHALL require `conversation_session.id_pedido` to be non-null and SHALL require the resolved `pedido_producto_id` to belong to that pedido. The ownership check is delegated to `PedidoProductoService.get_for_pedido`, which raises `PedidoProductoNotFound` when the line is absent or belongs to another pedido.

#### Scenario: Missing pedido is rejected
- **WHEN** `conversation_session.id_pedido is None`
- **THEN** the handler returns `status == "rejected"` without invoking the service

#### Scenario: Order line from another pedido is rejected
- **WHEN** the resolved `pedido_producto_id` exists but belongs to a different pedido
- **THEN** the handler returns `status == "rejected"` preserving the original intent

### Requirement: Decrement behavior

When `cantidad` is present and is strictly less than the current order-line quantity, the handler SHALL decrement the order line by that amount through `PedidoProductoService.update(pedido_producto_id, cantidad=current - cantidad)`.

#### Scenario: Partial removal decrements the line
- **WHEN** a ready intent with `cantidad=2` is dispatched and the current line has `cantidad=3`
- **THEN** the handler returns `executed` and the persisted line has `cantidad=1`

### Requirement: Complete removal behavior

When `cantidad` is omitted or equals the current line quantity, the handler SHALL delete the order line through `PedidoProductoService.delete(pedido_producto_id)`.

#### Scenario: Omitted quantity deletes the line
- **WHEN** a ready intent with no `cantidad` is dispatched and the line has `cantidad=3`
- **THEN** the handler returns `executed` and the persisted line is deleted

#### Scenario: Exact quantity deletes the line
- **WHEN** a ready intent with `cantidad=2` is dispatched and the line has `cantidad=2`
- **THEN** the handler returns `executed` and the persisted line is deleted

### Requirement: Excess quantity rejection

When `cantidad` is greater than the current line quantity, the handler SHALL return `status == "rejected"` and SHALL NOT mutate the order line. The handler SHALL include enough information in `resolved_data` for the response builder to phrase a deterministic rejection that quotes the current quantity.

#### Scenario: Excess quantity is rejected
- **WHEN** a ready intent with `cantidad=4` is dispatched and the line has `cantidad=2`
- **THEN** the handler returns `status == "rejected"`, `resolved_data["cantidad_actual"] == 2`, and the order line is unchanged

### Requirement: Result data

On success the handler SHALL return a new `ProcessedIntent` with `status == "executed"`, the original `intent`, `source_text`, `recognizer`, `handler`, `resolved_data`, `requirements`, and `candidate_ids` preserved, plus `resolved_data` enriched with `producto_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `cantidad_removida`, `cantidad_restante`, and `linea_eliminada: bool`.

#### Scenario: Successful execution enriches result data
- **WHEN** the order line is decremented or deleted successfully
- **THEN** `resolved_data` carries the documented enrichment keys and the original fields are preserved

#### Scenario: Deleted vs decremented line is distinguishable
- **WHEN** the order line is deleted
- **THEN** `resolved_data["linea_eliminada"] is True`; when decremented, `resolved_data["linea_eliminada"] is False`

### Requirement: Business and technical failure handling

Expected business-rule failures (missing pedido, wrong ownership, excess quantity, invalid resolved values, borrador-only guard from the service) SHALL return `status == "rejected"`. Unexpected technical failures MAY return `status == "failed"`. The handler SHALL NOT silently swallow exceptions or translate errors into `HTTPException`.

#### Scenario: Non-draft pedido is rejected
- **WHEN** the associated pedido is not in `borrador`
- **THEN** the handler returns `status == "rejected"` through the existing service behavior

#### Scenario: Unexpected exception yields failed
- **WHEN** the service raises an exception type not in the rejected mapping
- **THEN** the handler returns `status == "failed"` and preserves the original intent fields

### Requirement: Handler boundaries

The handler SHALL NOT perform SQLAlchemy queries, access repositories directly, call FastAPI routers, generate responses, clear pending context, promote queues, commit, or rollback.

#### Scenario: Handler has no HTTP or database implementation
- **WHEN** the handler source is inspected
- **THEN** it contains no SQLAlchemy query, repository access, router call, or response generation

#### Scenario: Context state is preserved by the handler
- **WHEN** the handler executes successfully
- **THEN** `pending_intents` and `context_type` remain unchanged

### Requirement: Public surface is limited

The handler module SHALL export only `execute_quitar_producto` through `__all__` and SHALL NOT add a generic handler abstraction.

#### Scenario: Single public handler symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["execute_quitar_producto"]`

### Requirement: Minimum repository and service operations

The system SHALL add the following minimum operations to the existing `PedidoProductoRepository` and `PedidoProductoService` modules, without changing other repository/service signatures or introducing new abstractions:

- `PedidoProductoRepository.list_by_pedido(db, pedido_id) -> list[PedidoProducto]` (eager-loads `producto_presentacion` and its `producto` so the handler can resolve display names without N+1).
- `PedidoProductoRepository.get_for_pedido(db, pedido_id, pedido_producto_id) -> PedidoProducto | None`.
- `PedidoProductoService.list_by_pedido(db, pedido_id) -> list[PedidoProducto]`.
- `PedidoProductoService.get_for_pedido(db, pedido_id, pedido_producto_id) -> PedidoProducto`.
- `PedidoProductoService.update(db, pedido_producto_id, *, cantidad)` (already exposed from subphase 2.14; reused as-is).
- `PedidoProductoService.delete(db, pedido_producto_id)` (already exposed from subphase 2.14; reused as-is).

#### Scenario: list_by_pedido returns the current draft lines
- **WHEN** `PedidoProductoService.list_by_pedido(db, pedido_id)` is called against a draft pedido with three lines
- **THEN** the returned list has exactly those three lines, eagerly loaded with product and presentation, in their persisted order

#### Scenario: get_for_pedido raises when the line is absent
- **WHEN** `PedidoProductoService.get_for_pedido(db, pedido_id, pedido_producto_id)` is called with a missing id
- **THEN** it raises `PedidoProductoNotFound` and the handler treats it as `rejected`
