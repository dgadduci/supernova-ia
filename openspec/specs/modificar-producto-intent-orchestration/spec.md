# Capability: modificar-producto-intent-orchestration

## Purpose

Provide the initial and refinement orchestration for `modificar_producto`, including the dedicated `PRODUCT_MODIFICATION` context type, the explicit `source_selection` / `destination_selection` stages, and the resolver that refines source candidates first and destination candidates second without broadening either domain back to the full Pedido or full catalog.

## Requirements

### Requirement: Initial orchestration module location

The system SHALL expose `process_initial_modificar_producto` from `backend/intents/orchestration/modificar_producto_initial.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Initial orchestrator is importable from the modern intents orchestration package

- **WHEN** a module executes `from backend.intents.orchestration.modificar_producto_initial import process_initial_modificar_producto`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Initial orchestrator signature

The system SHALL expose `process_initial_modificar_producto(db: DatabaseSession, session: ConversationSession, source_text: str) -> ProcessedIntent` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `process_initial_modificar_producto(db, session, "cambiá la pizza de muzzarella chica por una grande")`
- **THEN** the orchestrator returns a `ProcessedIntent` without raising

### Requirement: Active draft Pedido resolution

The orchestrator SHALL resolve the active draft Pedido through existing services (never through direct SQLAlchemy queries) before performing any candidate matching. When `session.id_pedido` is `None`, the orchestrator SHALL return a `rejected` `ProcessedIntent` without creating a pending context.

#### Scenario: Missing active draft Pedido is rejected

- **WHEN** `session.id_pedido is None` and `process_initial_modificar_producto(db, session, message)` is invoked
- **THEN** the function returns `ProcessedIntent(status="rejected", intent="modificar_producto")` without mutating any state

### Requirement: Source and destination candidate loading

The orchestrator SHALL load source candidates from `PedidoProductoService.list_by_pedido` and destination candidates from the existing product-query service for the comercio. It SHALL NOT issue SQLAlchemy queries directly.

#### Scenario: Orchestrator delegates to services for candidate loading

- **WHEN** `process_initial_modificar_producto(db, session, message)` runs
- **THEN** the recognizer or services are the only modules that issue SQLAlchemy queries; the orchestrator module itself does not call `select()` or `execute()`

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

### Requirement: Initial orchestrator does not commit, rollback, or generate responses

The orchestrator SHALL NOT issue `db.commit()`, `db.rollback()`, `db.flush()`, or generate a customer-facing response. Persistence and commit/rollback remain the caller's responsibility.

#### Scenario: Initial orchestrator performs no commit or rollback

- **WHEN** `process_initial_modificar_producto(db, session, message)` returns for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the orchestrator module

### Requirement: New ContextType value PRODUCT_MODIFICATION

`SESSION_CONTEXT_TYPE` SHALL expose `PRODUCT_MODIFICATION` with a distinct string value (`"product_modification"`). The existing `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION` values SHALL remain unchanged.

#### Scenario: PRODUCT_MODIFICATION is a new enum value

- **WHEN** `SESSION_CONTEXT_TYPE` is enumerated
- **THEN** it contains the existing values `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION` plus the new value `PRODUCT_MODIFICATION`

#### Scenario: PRODUCT_MODIFICATION has a distinct string value

- **WHEN** `ContextType.PRODUCT_MODIFICATION.value` is read
- **THEN** it equals the literal string `"product_modification"`

### Requirement: ContextTypeResolver routes modificar_producto to PRODUCT_MODIFICATION

`ContextTypeResolver.resolve_context_type` SHALL return `PRODUCT_MODIFICATION` when the active intent is `modificar_producto` and SHALL continue returning `PRODUCT_SELECTION` for `agregar_producto` and `ORDER_LINE_SELECTION` for `quitar_producto`.

#### Scenario: modificar_producto produces PRODUCT_MODIFICATION

- **WHEN** the active intent is `modificar_producto`
- **THEN** `ContextTypeResolver.resolve_context_type(db, session)` returns `ContextType.PRODUCT_MODIFICATION`

#### Scenario: Existing intents keep their context types

- **WHEN** the active intent is `agregar_producto` or `quitar_producto`
- **THEN** `ContextTypeResolver.resolve_context_type` returns `ContextType.PRODUCT_SELECTION` or `ContextType.ORDER_LINE_SELECTION` respectively, unchanged from today

### Requirement: Pending-context resolver module location

The system SHALL expose `resolve_product_modification` from `backend/intents/context/product_modification_resolver.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Resolver is importable from the modern intents context package

- **WHEN** a module executes `from backend.intents.context.product_modification_resolver import resolve_product_modification`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Pending-context resolver signature

The system SHALL expose `resolve_product_modification(db: DatabaseSession, session: ConversationSession, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `resolve_product_modification(db, session, message, active_intent)`
- **THEN** the resolver returns a `ProcessedIntent` without raising

### Requirement: Source refinement narrows source candidates only

When the active intent's `stage == "source_selection"`, the resolver SHALL refine `source_candidate_ids` exclusively against the current source candidate set, never broadening back to the full PedidoProducto history or the full catalog.

#### Scenario: Source refinement narrows within current candidates

- **WHEN** the active intent has `source_candidate_ids == [<id_a>, <id_b>]` and the message uniquely selects `<id_a>`
- **THEN** the resolver returns `ProcessedIntent(status="ready", stage="destination_selection", resolved_data={"source_candidate_ids": [<id_a>], "destination_candidate_ids": [...], "cantidad": <preserved>})` if the destination is still ambiguous, or `status="ready"` if the destination is also unique

#### Scenario: Source refinement preserves destination candidates

- **WHEN** the active intent has `destination_candidate_ids == [<id_x>, <id_y>]` and the resolver refines source candidates
- **THEN** `destination_candidate_ids` in the returned `ProcessedIntent` equals the prior `destination_candidate_ids` unchanged

#### Scenario: Source refinement never broadens to the full Pedido

- **WHEN** the active intent has `source_candidate_ids == [<id_a>, <id_b>]`
- **THEN** the resolver does not add any `PedidoProducto.id` outside that set to `source_candidate_ids`

### Requirement: Destination refinement narrows destination candidates only

When the active intent's `stage == "destination_selection"`, the resolver SHALL refine `destination_candidate_ids` exclusively against the current destination candidate set, never broadening back to the full active catalog.

#### Scenario: Destination refinement narrows within current candidates

- **WHEN** the active intent has `destination_candidate_ids == [<id_x>, <id_y>, <id_z>]` and the message uniquely selects `<id_y>`
- **THEN** the resolver returns `ProcessedIntent(status="ready", resolved_data={"pedido_producto_origen_id": <preserved>, "producto_presentacion_destino_id": <id_y>, "cantidad": <preserved>})`

#### Scenario: Destination refinement preserves source candidates

- **WHEN** the active intent has a unique resolved source ID and `destination_candidate_ids == [<id_x>, <id_y>, <id_z>]`
- **THEN** the resolver preserves the unique source ID in the returned `ProcessedIntent` unchanged

### Requirement: Resolution order

When both domains are unresolved, the resolver SHALL refine source first and destination second. The resolver SHALL NOT advance to `destination_selection` until source becomes unique.

#### Scenario: Both ambiguous starts in source_selection

- **WHEN** the active intent has `stage == "source_selection"` and more than one source candidate
- **THEN** the resolver never advances to `destination_selection` until exactly one source candidate remains

#### Scenario: Source becomes unique, then destination

- **WHEN** the active intent has `stage == "source_selection"`, exactly one source candidate remains after refinement, and destination candidates are still ambiguous
- **THEN** the resolver returns `ProcessedIntent(stage="destination_selection", resolved_data={"source_candidate_ids": [<id>], "destination_candidate_ids": [...], "cantidad": <preserved>})`

### Requirement: Invalid source or destination candidate returns rejected

When the message resolves to a source ID outside the current `source_candidate_ids`, or to a destination ID outside the current `destination_candidate_ids`, the resolver SHALL return a `rejected` `ProcessedIntent` without mutating the Pedido and without broadening the candidate set.

#### Scenario: Invalid source candidate is rejected

- **WHEN** the message resolves to a `PedidoProducto.id` not in `source_candidate_ids`
- **THEN** the resolver returns `ProcessedIntent(status="rejected", intent="modificar_producto")` and the Pedido is unchanged

#### Scenario: Invalid destination candidate is rejected

- **WHEN** the message resolves to a `ProductoPresentacion.id` not in `destination_candidate_ids`
- **THEN** the resolver returns `ProcessedIntent(status="rejected", intent="modificar_producto")` and the Pedido is unchanged

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

### Requirement: Resolver does not commit, rollback, or generate responses

The resolver SHALL NOT issue `db.commit()`, `db.rollback()`, or generate a customer-facing response. Persistence and response generation remain downstream responsibilities.

#### Scenario: Resolver performs no commit or rollback

- **WHEN** `resolve_product_modification(db, session, message, active_intent)` returns for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the resolver module

### Requirement: Public surface is limited

Both `process_initial_modificar_producto` and `resolve_product_modification` modules SHALL export only their single public function through `__all__`.

#### Scenario: Initial orchestrator exports one symbol

- **WHEN** `backend.intents.orchestration.modificar_producto_initial.__all__` is inspected
- **THEN** it equals `["process_initial_modificar_producto"]`

#### Scenario: Resolver exports one symbol

- **WHEN** `backend.intents.context.product_modification_resolver.__all__` is inspected
- **THEN** it equals `["resolve_product_modification"]`

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

### Requirement: Real-flow initial orchestration invariants

When the user message arrives through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or through the interactive CLI driver, `process_initial_modificar_producto` SHALL preserve the 3.32.1 invariants: it SHALL NOT substitute `1` for an omitted quantity; it SHALL persist `cantidad is None` as the omitted-quantity sentinel across turns; it SHALL preserve the resolved source ID and the original quantity across destination-selection turns; it SHALL NOT mutate the source before the destination is ready; it SHALL emit exactly one `ProcessedIntent` per message.

#### Scenario: HTTP endpoint drives the omitted-quantity invariant

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** `process_initial_modificar_producto` returns a `ready` `ProcessedIntent` whose `resolved_data["cantidad"]` is `None` (not `1`); the orchestrator persists the omitted-quantity sentinel without substitution; the handler re-reads the source quantity and the destination row has `cantidad == 4`

#### Scenario: CLI driver drives the omitted-quantity invariant

- **WHEN** the interactive CLI driver at `backend/scripts/cli_chat_client.py` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the orchestrator returns a `ready` `ProcessedIntent` whose `resolved_data["cantidad"]` is `None`; the handler re-reads `cantidad == 4`; the destination row has `cantidad == 4`

#### Scenario: HTTP endpoint preserves source when destination is rejected

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the orchestrator returns a `rejected` `ProcessedIntent` with `reason="no_destination_candidates"`; the source row remains `cantidad == 5`; no destination row is created; `Session.context_type` is `None`

#### Scenario: CLI driver preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the orchestrator returns a `rejected` `ProcessedIntent`; the source row remains `cantidad == 5`; no destination row is created; the printed order table reflects the unchanged Pedido

### Requirement: Real-flow pending-context preservation

When the user message arrives through the real HTTP endpoint or the interactive CLI driver, the pending-context lifecycle MUST hold: an `executed` outcome clears the pending context; a definitive `rejected` outcome clears the pending context; an `failed` outcome preserves the pending context; a raised technical exception propagates for rollback.

#### Scenario: HTTP clears the pending context after definitive outcome

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message whose outcome is `executed` or `rejected`
- **THEN** the `Session.context_type` is `None` and the persisted `pending_intents` no longer carries the `modificar_producto` active intent

#### Scenario: CLI clears the pending context after definitive outcome

- **WHEN** the interactive CLI driver processes any `modificar_producto` message whose outcome is `executed` or `rejected`
- **THEN** the next CLI message processes as a fresh message (no stale `modificar_producto` clarification prompt)

### Requirement: Real-flow single ProcessedIntent invariant

When driven by the real HTTP endpoint or the interactive CLI driver, the initial orchestrator MUST emit exactly one `ProcessedIntent` per `modificar_producto` message; the system MUST NOT decompose the modification into separate `quitar_producto` and `agregar_producto` outcomes.

#### Scenario: HTTP emits one ProcessedIntent for the modification

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** `process_incoming_message_transactional` returns exactly one `ProcessedIntent` whose `intent == "modificar_producto"`

#### Scenario: CLI emits one ProcessedIntent for the modification

- **WHEN** the interactive CLI driver processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the CLI prints exactly one modification response; no separate `Quité` and `Agregué` responses appear in the printed output for the same modification
