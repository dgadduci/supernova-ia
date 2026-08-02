# Capability: modificar-producto-atomicity-quantity

## Purpose

Codify the atomic quantity-preserving contract for `modificar_producto`. The flow operates as one atomic business operation: validate source → validate quantity → validate destination → validate price and availability → calculate complete mutation → decrement or delete source → create or increment destination → one transaction commit. The destination quantity always equals the transferred source quantity; the destination quantity SHALL never default to `1`. The source row SHALL NOT be mutated before every destination validation has passed. One modification message SHALL produce exactly one `ProcessedIntent` and exactly one `CustomerResponse`.

## Requirements

### Requirement: Authoritative quantity rule

The system SHALL treat `cantidad` as the quantity being transferred from the source PedidoProducto line to the destination. When the user explicitly supplies a modification quantity, the system SHALL use that quantity for both the source decrement or removal and the destination increment or creation. When the user omits the quantity, the system SHALL use the complete current quantity of the source PedidoProducto line and SHALL apply that same quantity to the destination. The destination quantity SHALL NOT default to `1`.

#### Scenario: Omitted quantity transfers the full source quantity

- **WHEN** the source PedidoProducto line has `cantidad == 4` and the user message omits the modification quantity
- **THEN** `cantidad_a_modificar == 4`, the source line is removed, and the destination receives `cantidad == 4`

#### Scenario: Explicit partial quantity transfers only that amount

- **WHEN** the source PedidoProducto line has `cantidad == 5` and the user message specifies `cantidad == 2`
- **THEN** `cantidad_a_modificar == 2`, the source line is decremented to `cantidad == 3`, and the destination receives `cantidad == 2`

#### Scenario: Explicit full quantity equals source quantity

- **WHEN** the source PedidoProducto line has `cantidad == 5` and the user message specifies `cantidad == 5`
- **THEN** `cantidad_a_modificar == 5`, the source line is removed, and the destination receives `cantidad == 5`

### Requirement: Destination quantity is never defaulted to one

The system SHALL NOT substitute `1` for an omitted modification quantity at any layer of the `modificar_producto` pipeline. The recognizer, the initial orchestrator, the pending-context resolver, the handler, and the service SHALL treat `cantidad is None` as the omitted-quantity sentinel. The service SHALL compute `cantidad_a_modificar` exclusively from the explicit `cantidad` argument or the re-read current source-line quantity.

#### Scenario: Recognizer never returns one for omitted quantity

- **WHEN** `recognize_modificar_producto(db, session, "cambia las empanadas por carne picante")` runs
- **THEN** the returned dict has `cantidad is None`

#### Scenario: Resolver never substitutes one for omitted quantity

- **WHEN** the active pending context has `resolved_data["cantidad"] is None` and the resolver advances from `source_selection` to `destination_selection`
- **THEN** the returned `ProcessedIntent.resolved_data["cantidad"]` is still `None`

#### Scenario: Handler never substitutes one for omitted quantity

- **WHEN** the handler invokes the service with `cantidad is None`
- **THEN** the service computes `cantidad_a_modificar` from the re-read current source-line quantity and never from `1`

### Requirement: Source quantity is re-read at execution time when omitted

When `cantidad is None` in the resolved intent, `execute_modificar_producto` SHALL re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, immediately before invoking the service. The re-read value SHALL be passed to the service as the explicit transfer quantity. The recognizer, initial orchestrator, and pending-context resolver SHALL NOT cache or substitute a quantity in place of the re-read.

#### Scenario: Omitted quantity re-read uses current source quantity

- **WHEN** the source PedidoProducto currently has `cantidad == 4` and the resolved intent has `cantidad is None`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 4`, passes it to the service as the explicit quantity, and the destination receives `cantidad == 4`

#### Scenario: Source quantity changed since resolution is detected

- **WHEN** the source PedidoProducto currently has `cantidad == 3` even though the resolver previously persisted `cantidad == 4`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 3`, passes it to the service, and the destination receives `cantidad == 3`

### Requirement: Validation before any source mutation

`PedidoProductoService.modify_product` SHALL perform every destination validation before any source row is mutated. The validations SHALL run, in order: load and validate the draft Pedido; load and validate the source PedidoProducto; compute `cantidad_a_modificar`; validate that `cantidad_a_modificar` does not exceed the source quantity; load and validate the destination `ProductoPresentacion` (existence, same comercio, active, available, presentation active); run the equivalent-modification guard; run the destination consolidation lookup; validate the destination price availability for a new line. Only after every validation succeeds SHALL the service mutate the source and the destination. The service SHALL NOT commit, rollback, flush, refresh, expire, or begin.

#### Scenario: Unknown destination preserves source line

- **WHEN** the user sends `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido that contains `Empanada de Jamón y Queso x5`, the destination `caramelo` is not in the comercio catalog, and the source quantity is `5`
- **THEN** the service returns `rejected` with `reason="destination_unavailable"`, the source line remains `cantidad == 5`, no destination line is created, and the Pedido is unchanged

#### Scenario: Validation order prohibits source mutation before destination validation

- **WHEN** `PedidoProductoService.modify_product` is invoked
- **THEN** the source row's `cantidad` and `id` are unchanged until every destination validation has returned successfully

#### Scenario: No commit between source removal and destination addition

- **WHEN** the service succeeds
- **THEN** the SQLAlchemy session has not been committed, rolled back, or flushed between the source mutation and the destination mutation; the outer transactional processor commits once at the end

### Requirement: Destination recognition failure preserves Pedido

When destination recognition produces zero valid candidates (the destination product does not exist in the comercio catalog, is inactive, is unavailable, belongs to a different comercio, or is equivalent to the source), the system SHALL return a definitive `rejected` `ProcessedIntent` without calling the mutation service, without calling any source removal service, and without mutating the Pedido. Any active pending context SHALL be cleared according to the existing corrected lifecycle.

#### Scenario: Destination recognition returns zero candidates

- **WHEN** the user sends `cambia las empanadas por un caramelo` and `caramelo` is not in the comercio catalog
- **THEN** the orchestrator returns `rejected` and no source mutation occurs

#### Scenario: Destination candidate is inactive or unavailable

- **WHEN** the destination `ProductoPresentacion` exists but is inactive, unavailable, or belongs to a different comercio
- **THEN** the orchestrator returns `rejected` and no source mutation occurs

#### Scenario: Destination equals source

- **WHEN** the source line's `producto_presentacion_id` equals the resolved destination's `producto_presentacion_id`
- **THEN** the orchestrator returns `rejected` with `reason="equivalent_modification"` and no source mutation occurs

### Requirement: Destination ambiguity preserves Pedido

When several destinations are possible, the system SHALL remain in `pending_resolution` with `stage="destination_selection"`, SHALL preserve the source ID and the omitted-or-explicit quantity, SHALL NOT mutate the Pedido, and SHALL ask only for destination clarification.

#### Scenario: Ambiguous destination returns destination_selection without mutation

- **WHEN** the source is unique and the destination has more than one valid candidate
- **THEN** the system returns `ProcessedIntent(status="pending_resolution", stage="destination_selection", resolved_data={"source_candidate_ids": [<id>], "destination_candidate_ids": [...], "cantidad": <preserved>})`, no PedidoProducto row is mutated, and the Pedido is unchanged

#### Scenario: Destination clarification after omitted quantity

- **WHEN** the source has `cantidad == 4`, the first message omits the quantity, and a follow-up message resolves the destination
- **THEN** the destination receives `cantidad == 4`, never `1`

#### Scenario: Destination clarification after explicit quantity

- **WHEN** the source has `cantidad == 5`, the first message specifies `cantidad == 2`, and a follow-up message resolves the destination
- **THEN** the source is decremented to `cantidad == 3` and the destination receives `cantidad == 2`

### Requirement: Handler never decomposes the modification

`execute_modificar_producto` SHALL call `PedidoProductoService.modify_product` exactly once per successful validation path. The handler SHALL NOT call `execute_quitar_producto`, SHALL NOT call `execute_agregar_producto`, SHALL NOT manually decrement the source, SHALL NOT manually create the destination, SHALL NOT emit an executed removal before the destination is ready, and SHALL NOT commit or rollback. The handler SHALL return exactly one `ProcessedIntent` per modification message.

#### Scenario: Handler never invokes quitar_producto

- **WHEN** the handler source is inspected
- **THEN** it does not import `execute_quitar_producto` or `execute_quitar_producto` aliases

#### Scenario: Handler never invokes agregar_producto

- **WHEN** the handler source is inspected
- **THEN** it does not import `execute_agregar_producto` or `execute_agregar_producto` aliases

#### Scenario: Handler returns exactly one ProcessedIntent

- **WHEN** `execute_modificar_producto(db, session, intent)` returns
- **THEN** the function returns exactly one `ProcessedIntent`; never a tuple, never a list, never a sequence of business outcomes

### Requirement: Single customer response per modification

The incoming-message response orchestrator SHALL translate one `modificar_producto` outcome into one `CustomerResponse` through `build_modificar_producto_response`. The system SHALL NOT produce a remove response followed by an add response, SHALL NOT produce two `CustomerResponse` instances per modification, and SHALL NOT split the modification across multiple response builders.

#### Scenario: Exactly one CustomerResponse per modification

- **WHEN** `process_incoming_message_transactional(db, session, message)` returns for a `modificar_producto` message
- **THEN** the response orchestrator produces exactly one `CustomerResponse` whose `intent == "modificar_producto"`

#### Scenario: No separate remove and add responses

- **WHEN** the user sends `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the rendered `CustomerResponse.message` is the single modification message; the response does not contain `Quité` and `Agregué` substrings together

### Requirement: Price snapshot rules preserved

When the destination PedidoProducto already exists in the same Pedido, the service SHALL preserve its stored price snapshot and SHALL NOT overwrite it. When the destination PedidoProducto does not exist, the service SHALL create the new line with the current destination catalog price snapshot read from the active `Precio` row. The source price SHALL remain unchanged after a partial decrement and SHALL NOT be looked up after the source has been mutated.

#### Scenario: Existing destination preserves stored price snapshot

- **WHEN** the destination line already exists in the same Pedido with a stored `precio_unitario` of `100.00`
- **THEN** after the modification the destination line still has `precio_unitario == 100.00`

#### Scenario: New destination uses current catalog price snapshot

- **WHEN** the destination line does not exist and the active `Precio` row for the destination `ProductoPresentacion` is `200.00`
- **THEN** after the modification the new destination line has `precio_unitario == 200.00`

#### Scenario: No price lookup after source mutation

- **WHEN** `PedidoProductoService.modify_product` runs to completion
- **THEN** the destination price lookup (`current_precio`) executes strictly before the source row is mutated

### Requirement: Destination consolidation preserved

When the destination PedidoProducto already exists in the same Pedido, the service SHALL increment that line in place, SHALL NOT create a duplicate `PedidoProducto` row for the same `(pedido_id, producto_presentacion_id)` pair, and SHALL add exactly `cantidad_a_modificar` to the existing line.

#### Scenario: Existing destination line is incremented in place

- **WHEN** the destination line already exists with `cantidad == 2` and `cantidad_a_modificar == 4`
- **THEN** after the modification the destination line has `cantidad == 6` and exactly one row exists for `(pedido_id, destination_producto_presentacion_id)`

### Requirement: Concurrency and stale-state rule preserved

If the source line changes between resolution and execution (for example because another `agregar_producto`, `quitar_producto`, or `modificar_producto` operation modified it within the same transaction), the re-read at execution time SHALL detect the divergence, SHALL re-validate source ownership and current quantity, and SHALL reject or raise the existing appropriate business exception. The system SHALL NOT introduce retry logic.

#### Scenario: Source quantity changed between resolution and execution

- **WHEN** the resolver persisted `cantidad_a_modificar == 4` but the source PedidoProducto currently has `cantidad == 2`
- **THEN** the handler re-reads `cantidad == 2` and the destination receives `cantidad == 2` (or the modification is rejected if the source quantity is now incompatible with the explicit `cantidad`)

#### Scenario: No retry logic is introduced

- **WHEN** the source quantity diverges across turns
- **THEN** the system rejects or proceeds without retrying the database operation

### Requirement: Pending-context lifecycle preserved

The system SHALL preserve the corrected pending-context lifecycle for `modificar_producto`: an `executed` outcome clears the pending context; a definitive `rejected` outcome clears the pending context; an `failed` outcome preserves the pending context; a raised technical exception propagates so the transactional wrapper rolls back. The lifecycle applies equally to the source-mutation, destination-mutation, and quantity-derivation paths.

#### Scenario: Executed clears pending context

- **WHEN** `execute_modificar_producto` returns `executed`
- **THEN** the pending context is cleared

#### Scenario: Definitive rejected clears pending context

- **WHEN** `execute_modificar_producto` returns `rejected` with a deterministic business reason
- **THEN** the pending context is cleared

#### Scenario: Failed preserves pending context

- **WHEN** `execute_modificar_producto` returns `failed`
- **THEN** the pending context is preserved

#### Scenario: Technical exception propagates

- **WHEN** `execute_modificar_producto` raises an unexpected exception
- **THEN** the exception propagates unchanged so the transactional wrapper's `db.rollback()` discards every staged write

### Requirement: Response messages for the corrected outcomes

The response builder SHALL render concise deterministic Spanish messages for the corrected outcomes, without LLM involvement, without prompt construction, and without exposing database identifiers.

#### Scenario: Executed omitted-quantity transfer message

- **WHEN** the modification succeeds with `cantidad_a_modificar == 4`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`
- **THEN** the rendered message is `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.`

#### Scenario: Executed explicit-quantity partial transfer message

- **WHEN** the modification succeeds with `cantidad_a_modificar == 2`, `cantidad_origen_restante == 2`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`
- **THEN** the rendered message is `Cambié 2 Empanadas de Verdura por 2 Empanadas de Carne Picante. Quedan 2 Empanadas de Verdura.`

#### Scenario: Rejected unknown destination preserves Pedido

- **WHEN** the modification is rejected because the destination is unknown to the comercio catalog
- **THEN** the rendered message is `No encontré el producto de reemplazo. Tu pedido no fue modificado.`

#### Scenario: Rejected unavailable destination preserves Pedido

- **WHEN** the modification is rejected because the destination is inactive or unavailable
- **THEN** the rendered message is `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`

#### Scenario: Rejected excess quantity preserves Pedido

- **WHEN** the modification is rejected because `cantidad` exceeds the current source quantity
- **THEN** the rendered message is `Solo tenés <cantidad_actual> Empanadas de Verdura para cambiar. Tu pedido no fue modificado.`

### Requirement: Regression scope unchanged

The correction SHALL preserve the `agregar_producto` and `quitar_producto` flows end-to-end, the unique `(pedido_id, producto_presentacion_id)` invariant, the existing `PedidoProductoService` public surface outside `modify_product`, the existing `PedidoProductoRepository` public surface, the existing transactional processor as the sole commit/rollback owner, and the existing CLI driver.

#### Scenario: agregar_producto flow unchanged

- **WHEN** the existing `agregar_producto` end-to-end and dispatcher tests run after the change
- **THEN** they pass without modification

#### Scenario: quitar_producto flow unchanged

- **WHEN** the existing `quitar_producto` end-to-end and dispatcher tests run after the change
- **THEN** they pass without modification

#### Scenario: Transactional processor remains the sole commit owner

- **WHEN** the change is inspected
- **THEN** `process_incoming_message_transactional` is the only module that calls `db.commit()` and `db.rollback()` for the modification path; the service, handler, recognizer, orchestrator, resolver, and response builder do not call them

### Requirement: Real-flow atomic-quantity contract

The atomic-quantity contract for `modificar_producto` MUST hold when the user message arrives through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or through the interactive CLI driver at `backend/scripts/cli_chat_client.py`, not only through hand-crafted orchestrator fixtures. Both reproduction phrases MUST produce the documented outcomes end-to-end through the real HTTP/CLI entry points.

#### Scenario: HTTP endpoint transfers the full source quantity on omitted quantity

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the source `PedidoProducto` row is removed; a destination `PedidoProducto` row exists with `cantidad == 4`; the rendered response message contains the explicit quantity `4` on both sides; the destination `cantidad` is never `1`

#### Scenario: CLI driver transfers the full source quantity on omitted quantity

- **WHEN** the interactive CLI driver receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the source `PedidoProducto` row is removed; the destination `PedidoProducto` row has `cantidad == 4`; the printed order table shows the destination line with `cantidad == 4` and no source line

#### Scenario: HTTP endpoint preserves source when destination is rejected

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`; no destination `PedidoProducto` row exists; the rendered response message confirms the Pedido is unchanged; the response orchestrator emits exactly one `CustomerResponse` whose `intent == "modificar_producto"`

#### Scenario: CLI driver preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`; no destination `PedidoProducto` row exists; the printed order table shows the source line unchanged; the printed customer response confirms the Pedido is unchanged

### Requirement: Real-flow regression matrix drives the seam

The system MUST add two test files that drive the real HTTP endpoint and the real CLI driver with both reproduction phrases:

- `backend/tests/test_modificar_producto_real_flow_http.py` — drives `POST /comercios/{id}/clientes/{id}/incoming-messages`.
- `backend/tests/test_modificar_producto_real_flow_cli.py` — drives `backend/scripts/cli_chat_client.py`.

The two test files MUST coexist with the existing 3.32.1 orchestrator-level suites; no existing test file is removed, renamed, or weakened.

#### Scenario: HTTP regression test asserts the rendered outcome

- **WHEN** the new HTTP regression test runs against `supernova_test`
- **THEN** it asserts the rendered `CustomerResponse.message`, the resulting `PedidoProducto` rows, and the `Session.context_type` for both reproduction phrases

#### Scenario: CLI regression test asserts the printed outcome

- **WHEN** the new CLI regression test runs against `supernova_test`
- **THEN** it asserts the printed customer response and the printed order table for both reproduction phrases

#### Scenario: Existing 3.32.1 tests remain green

- **WHEN** the new real-flow regression tests run alongside the existing orchestrator-level suites
- **THEN** every existing 3.32.1 test passes unchanged
