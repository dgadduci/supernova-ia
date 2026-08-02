# Capability: modificar-producto-intent-orchestration

## Purpose

Provide the initial and refinement orchestration for `modificar_producto`, including the dedicated `PRODUCT_MODIFICATION` context type, the explicit `source_selection` / `destination_selection` stages, and the resolver that refines source candidates first and destination candidates second without broadening either domain back to the full Pedido or full catalog. The orchestration SHALL preserve the omitted-quantity semantics across turns, SHALL NEVER substitute `1` for an omitted modification quantity, SHALL preserve the source quantity across destination clarification, and SHALL NEVER mutate the Pedido before both domains resolve uniquely.

## MODIFIED Requirements

### Requirement: Unique source and unique destination return ready

When the recognizer returns exactly one source candidate and exactly one destination candidate (and the source and destination are not equivalent), the orchestrator SHALL return a `ProcessedIntent(status="ready")` with `resolved_data["pedido_producto_origen_id"]` and `resolved_data["producto_presentacion_destino_id"]` populated, plus the preserved optional `cantidad`. The orchestrator SHALL NOT substitute `1` for an omitted quantity.

#### Scenario: Unique source and unique destination produce ready

- **WHEN** the recognizer emits exactly one source candidate, exactly one destination candidate, the source and destination are not equivalent, and the optional `cantidad` is valid
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="ready", intent="modificar_producto", resolved_data={"pedido_producto_origen_id": <id>, "producto_presentacion_destino_id": <id>, "cantidad": <qty or None>})`

#### Scenario: Omitted cantidad with unique domains produces ready with None cantidad

- **WHEN** the recognizer emits exactly one source candidate, exactly one destination candidate, and `cantidad is None`
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="ready", resolved_data={..., "cantidad": None})` and never substitutes `1`

### Requirement: Ambiguous source or destination returns pending_resolution

When the recognizer returns more than one source candidate or more than one destination candidate, the orchestrator SHALL return a `ProcessedIntent(status="pending_resolution", context_type="product_modification")` carrying the reduced candidate sets and an explicit `stage` field (`source_selection` when source is ambiguous, `destination_selection` when source is unique but destination is ambiguous). The orchestrator SHALL persist the omitted-quantity sentinel (`cantidad is None`) without substituting `1`. The orchestrator SHALL NOT overload one `candidate_ids` list with both identifier domains.

#### Scenario: Ambiguous source returns pending_resolution in source_selection

- **WHEN** the recognizer emits more than one source candidate
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="pending_resolution", context_type="product_modification", stage="source_selection", resolved_data={"source_candidate_ids": [...], "destination_candidate_ids": [...], "cantidad": <qty or None>})`

#### Scenario: Unique source but ambiguous destination returns pending_resolution in destination_selection

- **WHEN** the recognizer emits exactly one source candidate and more than one destination candidate
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="pending_resolution", context_type="product_modification", stage="destination_selection", resolved_data={"source_candidate_ids": [<id>], "destination_candidate_ids": [...], "cantidad": <qty or None>})` and the persisted `cantidad` is the omitted-quantity sentinel, never `1`

### Requirement: Source absent from Pedido returns rejected

When the recognizer returns zero source candidates or the active draft Pedido has zero lines, the orchestrator SHALL return a deterministic `ProcessedIntent(status="rejected", intent="modificar_producto")` without creating a pending context and without mutating the Pedido.

#### Scenario: Empty source catalog is rejected

- **WHEN** the active draft Pedido has zero `PedidoProducto` rows
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="rejected", intent="modificar_producto")` with `context_type is None` and the Pedido is unchanged

#### Scenario: Zero source candidates is rejected

- **WHEN** the recognizer emits zero source candidates
- **THEN** the orchestrator returns `ProcessedIntent(status="rejected", intent="modificar_producto")` with `context_type is None` and the Pedido is unchanged

### Requirement: Equivalent source and destination returns rejected

When the resolved source line already uses the same `producto_presentacion_id` as the resolved destination, the orchestrator SHALL return a deterministic `rejected` `ProcessedIntent` without mutating any state and without substituting `1` for an omitted quantity.

#### Scenario: Source equals destination is rejected

- **WHEN** `resolved_data["pedido_producto_origen_id"]` resolves to a line whose `producto_presentacion_id` equals the resolved destination's `producto_presentacion_id`
- **THEN** `process_initial_modificar_producto` returns `ProcessedIntent(status="rejected", intent="modificar_producto")` and no pending context is created

### Requirement: Destination unavailable returns rejected

When the resolved destination does not exist, is inactive, or is unavailable, the orchestrator SHALL return a deterministic `rejected` `ProcessedIntent` consistent with the existing contract, without mutating the Pedido.

#### Scenario: Inactive destination is rejected

- **WHEN** the recognizer resolves a destination whose `ProductoPresentacion` is inactive or unavailable
- **THEN** the orchestrator returns `ProcessedIntent(status="rejected", intent="modificar_producto")` and no pending context is created and the Pedido is unchanged

#### Scenario: Unknown destination is rejected

- **WHEN** the user message references a product that does not exist in the comercio catalog
- **THEN** the orchestrator returns `ProcessedIntent(status="rejected", intent="modificar_producto")` and no source row is mutated

### Requirement: Resolver preserves resolved data and quantity across stages

The resolver SHALL preserve any already-resolved source ID, already-resolved destination ID, and the optional `cantidad` when transitioning between stages. The resolver SHALL NOT substitute `1` for an omitted quantity and SHALL NOT mutate the Pedido while the destination is still ambiguous.

#### Scenario: Resolver preserves omitted cantidad across stages

- **WHEN** the active intent has `cantidad is None` and the resolver advances from `source_selection` to `destination_selection`
- **THEN** the returned `ProcessedIntent.resolved_data["cantidad"]` is still `None` and never `1`

#### Scenario: Resolver preserves resolved source when refining destination

- **WHEN** the active intent has `resolved_data["pedido_producto_origen_id"] == <id>` and the resolver refines destination candidates
- **THEN** the returned `ProcessedIntent.resolved_data["pedido_producto_origen_id"]` equals `<id>` unchanged

#### Scenario: Destination ambiguity preserves Pedido

- **WHEN** the source is unique and the destination is ambiguous
- **THEN** the resolver returns `pending_resolution` without mutating any `PedidoProducto` row and the Pedido is unchanged

## ADDED Requirements

### Requirement: Omitted-quantity preservation across turns

The orchestrator and the resolver SHALL persist `cantidad is None` as the omitted-quantity sentinel across turns. The handler SHALL re-read the current source quantity at execution time and SHALL NEVER substitute `1` for an omitted quantity. The destination quantity SHALL always equal the transferred source quantity when the user omitted the quantity.

#### Scenario: Destination clarification after omitted quantity never defaults to one

- **WHEN** the source has `cantidad == 4`, the first message omits the quantity, and a follow-up message resolves the destination
- **THEN** the destination receives `cantidad == 4`, never `1`

#### Scenario: Destination clarification after explicit quantity

- **WHEN** the source has `cantidad == 5`, the first message specifies `cantidad == 2`, and a follow-up message resolves the destination
- **THEN** the source is decremented to `cantidad == 3` and the destination receives `cantidad == 2`

#### Scenario: Resolver never substitutes one for omitted quantity

- **WHEN** the active pending context has `cantidad is None` and the resolver refines any candidate set
- **THEN** the returned `ProcessedIntent.resolved_data["cantidad"]` remains `None`

### Requirement: Validation before any source mutation

The orchestrator and the resolver SHALL NOT issue source mutations (decrement, delete, or row removal) before the destination resolves uniquely and every destination validation has passed. The mutation is delegated to `PedidoProductoService.modify_product` and is never performed by the orchestrator or the resolver directly.

#### Scenario: Orchestrator does not mutate the Pedido before destination is ready

- **WHEN** `process_initial_modificar_producto` returns `pending_resolution`
- **THEN** no `PedidoProducto` row has been mutated, deleted, or removed by the orchestrator

#### Scenario: Resolver does not mutate the Pedido before destination is ready

- **WHEN** `resolve_product_modification` returns `pending_resolution`
- **THEN** no `PedidoProducto` row has been mutated, deleted, or removed by the resolver