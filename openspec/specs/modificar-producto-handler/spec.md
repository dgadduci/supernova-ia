# Capability: modificar-producto-handler

## Purpose

Provide the ready handler and the atomic service operation for `modificar_producto`. The handler validates intent shape, delegates the atomic mutation to `PedidoProductoService.modify_product`, and never mutates rows manually. The service enforces every business rule (draft Pedido, ownership, source validity, destination validity, quantity semantics, equivalent-modification guard, unique-line invariant, price-snapshot preservation) inside the existing transaction boundary.

## Requirements

### Requirement: Handler module location

The system SHALL expose `execute_modificar_producto` from `backend/intents/handlers/modificar_producto_handler.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Handler is importable from the modern intents handlers package

- **WHEN** a module executes `from backend.intents.handlers.modificar_producto_handler import execute_modificar_producto`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Handler signature

The system SHALL expose `execute_modificar_producto(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> ProcessedIntent` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `execute_modificar_producto(db, session, intent)` with a valid `ready` `modificar_producto` intent
- **THEN** the handler returns a `ProcessedIntent` without raising

### Requirement: Intent validation

The handler SHALL validate `intent.intent == "modificar_producto"`, `intent.status == "ready"`, `intent.handler == "modificar_producto"`, and the presence of `resolved_data["pedido_producto_origen_id"]` and `resolved_data["producto_presentacion_destino_id"]`. The handler SHALL reject without mutation when any validation fails.

#### Scenario: Invalid intent name is rejected

- **WHEN** `intent.intent != "modificar_producto"`
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected", intent="modificar_producto")` without calling the service

#### Scenario: Missing source identifier is rejected

- **WHEN** `resolved_data["pedido_producto_origen_id"]` is missing
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected")` without calling the service

#### Scenario: Missing destination identifier is rejected

- **WHEN** `resolved_data["producto_presentacion_destino_id"]` is missing
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected")` without calling the service

#### Scenario: Non-ready status is rejected

- **WHEN** `intent.status != "ready"`
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected")` without calling the service

### Requirement: Source identifier type validation

The handler SHALL validate that `pedido_producto_origen_id` is an integer and that the optional `cantidad` is a positive integer when present. The handler SHALL reject without mutation when validation fails.

#### Scenario: Non-integer source identifier is rejected

- **WHEN** `resolved_data["pedido_producto_origen_id"]` is not an integer
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected")` without calling the service

#### Scenario: Zero or negative cantidad is rejected

- **WHEN** `resolved_data["cantidad"]` is `0` or negative
- **THEN** `execute_modificar_producto` returns `ProcessedIntent(status="rejected")` without calling the service

### Requirement: Service delegation

The handler SHALL delegate the atomic mutation to `PedidoProductoService.modify_product` exactly once per successful validation path. The handler SHALL NOT issue SQLAlchemy queries directly and SHALL NOT perform source decrement or destination increment manually.

#### Scenario: Valid intent delegates to the service

- **WHEN** the intent passes all validation checks
- **THEN** `execute_modificar_producto` calls `PedidoProductoService.modify_product(db, pedido_id, pedido_producto_origen_id, producto_presentacion_destino_id, cantidad)` exactly once

#### Scenario: Handler issues no SQLAlchemy queries

- **WHEN** `execute_modificar_producto(db, session, intent)` completes for any branch
- **THEN** no SQLAlchemy `select()`, `execute()`, `add()`, `delete()`, or relationship-loading call has been made by the handler module

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

### Requirement: Exception propagation

When the service raises an unexpected technical exception (for example `IntegrityError` or `OperationalError`), the handler SHALL allow the exception to propagate unchanged so the existing transactional processor's `db.rollback()` is preserved. The handler SHALL NOT catch broad `Exception` and SHALL NOT translate to `failed` for unexpected exceptions.

#### Scenario: IntegrityError propagates

- **WHEN** the service raises `sqlalchemy.exc.IntegrityError`
- **THEN** the handler re-raises the same exception and no `PedidoProducto` mutation persists

#### Scenario: Handler does not catch broad Exception

- **WHEN** the handler module source is inspected
- **THEN** it does not contain `except Exception:` or `except BaseException:` blocks

### Requirement: Source quantity re-read at execution time when omitted

When the resolved intent carries `cantidad is None`, the handler SHALL re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, immediately before invoking the service. The re-read value SHALL be passed to the service as the explicit transfer quantity. The handler SHALL NOT substitute `1` and SHALL NOT rely on a cached source quantity.

#### Scenario: Omitted quantity re-read uses current source quantity

- **WHEN** the source PedidoProducto currently has `cantidad == 4` and the resolved intent has `cantidad is None`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 4`, passes it to the service as the explicit quantity, and the destination receives `cantidad == 4`

#### Scenario: Source quantity changed since resolution is detected

- **WHEN** the source PedidoProducto currently has `cantidad == 3` even though the resolver previously persisted a different quantity
- **THEN** `execute_modificar_producto` re-reads `cantidad == 3` and passes it to the service; the destination receives `cantidad == 3`

### Requirement: No commit, rollback, or response generation in the handler

The handler SHALL NOT call `db.commit()`, `db.rollback()`, `db.flush()`, or generate a customer-facing response. Persistence and commit/rollback remain the caller's responsibility; response generation belongs to `build_modificar_producto_response`.

#### Scenario: Handler performs no commit or rollback

- **WHEN** `execute_modificar_producto(db, session, intent)` completes for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the handler module

#### Scenario: Handler does not import the response builder

- **WHEN** the handler module source is inspected
- **THEN** it does not import `build_modificar_producto_response` or any response-builder module

#### Scenario: No commit between source removal and destination addition

- **WHEN** the handler delegates to `PedidoProductoService.modify_product`
- **THEN** no commit, rollback, or flush has been issued between the source row mutation and the destination row mutation

### Requirement: Atomic service operation location

The system SHALL expose `modify_product` as a method of `PedidoProductoService` in `backend/services/pedido_producto_service.py` (the existing service module). The atomic mutation SHALL run inside the existing transaction boundary; the service SHALL NOT commit, rollback, or close the session.

#### Scenario: Service method is callable on PedidoProductoService

- **WHEN** `PedidoProductoService.modify_product(db, pedido_id, pedido_producto_origen_id, producto_presentacion_destino_id, cantidad)` is invoked with valid arguments
- **THEN** the service performs the atomic mutation and returns a `ModificationResult`

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

### Requirement: Equivalent source and destination rejected before mutation

The service SHALL compare the source line's `producto_presentacion_id` to the resolved destination's `producto_presentacion_id` before any mutation and SHALL return `rejected` with `reason="equivalent_modification"` when they are equal.

#### Scenario: Same presentation is rejected

- **WHEN** the source line's `producto_presentacion_id` equals the destination `ProductoPresentacion.id`
- **THEN** `PedidoProductoService.modify_product` returns `rejected` with `reason="equivalent_modification"` and the Pedido is unchanged

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

### Requirement: Destination consolidation invariant

The service SHALL reuse the existing unique `(pedido_id, producto_presentacion_id)` invariant. When the destination line already exists in the same Pedido, the service SHALL increment its existing row; when it does not exist, the service SHALL create exactly one new `PedidoProducto` row.

#### Scenario: Existing destination line is incremented in place

- **WHEN** a `PedidoProducto` row already exists for `(pedido_id, destination_producto_presentacion_id)`
- **THEN** the service increments that row's `cantidad` and does not create a parallel row

#### Scenario: New destination line is created exactly once

- **WHEN** no `PedidoProducto` row exists for `(pedido_id, destination_producto_presentacion_id)`
- **THEN** the service creates exactly one new row and does not create duplicates

### Requirement: Price snapshot rules

The service SHALL preserve the existing destination price snapshot when the destination line already exists, and SHALL populate the new destination line with the current destination catalog price snapshot when the destination line does not exist. The service SHALL NOT average or recalculate existing price snapshots, SHALL NOT modify the source line price after partial decrement, and SHALL NOT preserve any source price after full deletion.

#### Scenario: Existing destination line preserves its price snapshot

- **WHEN** the destination line already exists and the service increments it
- **THEN** the row's stored price snapshot equals the value it had before the modification, unchanged

#### Scenario: New destination line uses the current catalog price snapshot

- **WHEN** the destination line does not exist and the service creates it
- **THEN** the new row's price snapshot equals the current active `Precio` for the destination `ProductoPresentacion`

#### Scenario: Source price is unchanged after partial decrement

- **WHEN** `cantidad < source.cantidad`
- **THEN** the source row's stored price snapshot equals the value it had before the modification

### Requirement: Atomic transactional boundary

The service SHALL perform all mutations inside the existing transaction boundary opened by the caller. The service SHALL NOT call `db.commit()`, `db.rollback()`, `db.flush()`, `db.refresh()`, `db.expire()`, or `db.begin()`. The service SHALL NOT close the SQLAlchemy session.

#### Scenario: Service performs no commit or rollback

- **WHEN** `PedidoProductoService.modify_product(...)` returns for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the service

#### Scenario: Technical exception rolls back the transaction

- **WHEN** the mutation raises an unexpected exception after some writes have been staged
- **THEN** the exception propagates and the transactional wrapper's `db.rollback()` discards every staged write, leaving source and destination unchanged

### Requirement: Minimum repository surface

`PedidoProductoRepository` SHALL expose the minimum operations required for atomic modification: `get_for_pedido(db, pedido_id, pedido_producto_id)`, `decrement(db, pedido_producto_id, cantidad)`, `delete(db, pedido_producto_id)`, `increment(db, pedido_producto_id, cantidad)`, and `create_with_price_snapshot(db, pedido_id, producto_presentacion_id, cantidad, precio_unitario)`. Repository methods SHALL be DB-only; business validation and orchestration remain in the service.

#### Scenario: Repository methods are DB-only

- **WHEN** `PedidoProductoRepository` source is inspected
- **THEN** its new methods do not perform Pedido-state validation, ownership checks, or business orchestration; those concerns are implemented in `PedidoProductoService`

### Requirement: Public surface is limited

The handler module SHALL export only `execute_modificar_producto` through `__all__`. The service SHALL expose `modify_product` as a public method without introducing additional public helpers.

#### Scenario: Only one public symbol is exported from the handler

- **WHEN** `backend.intents.handlers.modificar_producto_handler.__all__` is inspected
- **THEN** it equals `["execute_modificar_producto"]`

### Requirement: Real-flow handler re-read invariant

When the resolved `ProcessedIntent` originates from the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or from the interactive CLI driver, `execute_modificar_producto` SHALL re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, SHALL pass the re-read value to `PedidoProductoService.modify_product` as the explicit transfer quantity, and SHALL NOT substitute `1`. The re-read MUST hold for both the exact reproduction phrases (`cambia las empanadas de verdura por empanadas carne picante` and `cambia las 5 empanadas de jamon y queso por un caramelo`), not only for hand-crafted `ProcessedIntent` fixtures.

#### Scenario: Real HTTP endpoint drives the omitted-quantity re-read

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 4`, passes `4` to `PedidoProductoService.modify_product`, and the destination `PedidoProducto` row has `cantidad == 4`; the destination `cantidad` is never `1`

#### Scenario: Real CLI driver drives the omitted-quantity re-read

- **WHEN** the interactive CLI driver at `backend/scripts/cli_chat_client.py` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the orchestrator builds the `ready` `ProcessedIntent` with `cantidad is None`, `execute_modificar_producto` re-reads `cantidad == 4`, passes `4` to the service, and the destination row has `cantidad == 4`

#### Scenario: Real pipeline does not substitute one for omitted quantity

- **WHEN** the real HTTP endpoint or the interactive CLI driver delivers a `modificar_producto` message with `cantidad is None`
- **THEN** the captured per-layer trace records `cantidad == 4` (the re-read source quantity) as the value passed to `PedidoProductoService.modify_product`; the trace never records `cantidad == 1` for an omitted-quantity message

### Requirement: Real-flow single ProcessedIntent invariant

When driven by the real HTTP endpoint or the interactive CLI driver, `execute_modificar_producto` SHALL return exactly one `ProcessedIntent` per modification message; the pipeline SHALL NOT produce a `quitar_producto` followed by an `agregar_producto` outcome for a single `modificar_producto` message.

#### Scenario: HTTP single ProcessedIntent invariant

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** `process_incoming_message_transactional` returns exactly one `ProcessedIntent` whose `intent == "modificar_producto"`; no `agregar_producto` and no `quitar_producto` outcome is emitted for the same message

#### Scenario: CLI single ProcessedIntent invariant

- **WHEN** the interactive CLI driver processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the CLI prints exactly one modification response; the printed output never contains both a `Quité` message and an `Agregué` message for the same modification

### Requirement: Real-flow validation-before-mutation invariant

When driven by the real HTTP endpoint or the interactive CLI driver, every destination validation MUST complete before any source mutation; no commit or flush SHALL occur between source removal and destination addition; the source `PedidoProducto` row SHALL remain unchanged when the destination is rejected.

#### Scenario: HTTP preserves source when destination is rejected

- **WHEN** the real HTTP endpoint receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`, no destination `PedidoProducto` row exists, and the rendered response message confirms the Pedido is unchanged

#### Scenario: CLI preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the printed order table shows the source line unchanged with `cantidad == 5`, no destination line appears, and the printed customer response confirms the Pedido is unchanged
