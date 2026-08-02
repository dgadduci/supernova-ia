# Capability: quitar-producto-intent-orchestration

## Purpose

Provide the initial and pending-context orchestration for `quitar_producto` — a single function that resolves the target `PedidoProducto` row uniquely from a customer message (or returns `pending_resolution` / `rejected` deterministically), and a dedicated `ORDER_LINE_SELECTION` context type plus resolver for refining ambiguous matches across turns without broadening candidates back to the commerce catalog.

## Requirements

### Requirement: Initial orchestration module location

The system SHALL expose `process_initial_quitar_producto` from `backend/intents/orchestration/quitar_producto_initial.py`.

#### Scenario: Initial orchestration is importable
- **WHEN** a module executes `from backend.intents.orchestration.quitar_producto_initial import process_initial_quitar_producto`
- **THEN** the import succeeds and the binding is callable

### Requirement: Initial orchestration signature

The system SHALL expose `process_initial_quitar_producto(db: DatabaseSession, session: ConversationSession, source_text: str) -> ProcessedIntent`.

#### Scenario: Function is callable with the documented signature
- **WHEN** a caller invokes `process_initial_quitar_producto(db, session, "quitá una pizza")`
- **THEN** the function returns a `ProcessedIntent` without raising

### Requirement: Resolve active draft pedido

The function SHALL require `session.id_pedido` to be non-null and SHALL load the draft pedido through existing services before any candidate resolution. When `session.id_pedido` is null, the function SHALL return a `ProcessedIntent(status="rejected")` without mutating any state.

#### Scenario: Active pedido is required
- **WHEN** `session.id_pedido is None`
- **THEN** the function returns a `rejected` `ProcessedIntent` carrying `intent="quitar_producto"`

#### Scenario: Active pedido is loaded through the service layer
- **WHEN** the function runs with a valid `session.id_pedido`
- **THEN** it resolves the pedido through existing services and does not run a SQLAlchemy query directly

### Requirement: Unique match becomes ready

When the recognizer returns exactly one candidate, the function SHALL populate `resolved_data["pedido_producto_id"]` from that candidate, mark the `pedido_producto_id` requirement as completed, propagate the optional `cantidad`, set `status="ready"`, and return the intent.

#### Scenario: Unique match returns ready
- **WHEN** the draft pedido contains one matching `PedidoProducto` row and no other line matches the message
- **THEN** the returned intent has `status="ready"`, `resolved_data["pedido_producto_id"]` equals that row's id, and `resolved_data["cantidad"]` equals the recognized quantity (or `None` when omitted)

### Requirement: Multiple matches become pending_resolution

When the recognizer returns more than one candidate, the function SHALL return a `ProcessedIntent(status="pending_resolution", context_type="order_line_selection")` whose `candidate_ids` equals the list of `pedido_producto_id` values from the candidates, SHALL propagate the recognized quantity in `resolved_data`, and SHALL NOT include products absent from the draft pedido.

#### Scenario: Ambiguous match returns pending resolution with current order lines
- **WHEN** the draft pedido contains three `Pizza` lines and the message is `quitá una pizza`
- **THEN** the returned intent has `status="pending_resolution"`, `context_type="order_line_selection"`, and `candidate_ids` lists exactly the three matching `pedido_producto_id` values

#### Scenario: Pending resolution preserves original quantity
- **WHEN** the original message was `quitá 2 empanadas`
- **THEN** `resolved_data["cantidad"]` remains `2` in the `pending_resolution` intent

### Requirement: No match is deterministic rejected

When the recognizer returns zero candidates and the draft pedido has at least one line, the function SHALL return a `ProcessedIntent(status="rejected")` with `intent="quitar_producto"` and SHALL NOT create a pending context with an empty candidate set.

#### Scenario: Empty candidate set is rejected without pending context
- **WHEN** the draft pedido contains lines that the recognizer does not match
- **THEN** the returned intent has `status="rejected"` and `candidate_ids == []`, and no pending intent is persisted

#### Scenario: Empty pedido is rejected without pending context
- **WHEN** the draft pedido has zero `PedidoProducto` rows
- **THEN** the returned intent has `status="rejected"` and no pending intent is persisted

### Requirement: ORDER_LINE_SELECTION context type

The system SHALL add `ContextType.ORDER_LINE_SELECTION` to the existing `SESSION_CONTEXT_TYPE` enum and SHALL wire it through `ContextTypeResolver.resolve_context_type` so an active `quitar_producto` ready intent resolves to `ORDER_LINE_SELECTION` and an active `agregar_producto` ready intent still resolves to `PRODUCT_SELECTION`.

#### Scenario: ORDER_LINE_SELECTION is a new enum value
- **WHEN** `SESSION_CONTEXT_TYPE` is inspected
- **THEN** it contains both `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION` as distinct string values

#### Scenario: ContextTypeResolver routes quitar_producto to ORDER_LINE_SELECTION
- **WHEN** a ready `ProcessedIntent(intent="quitar_producto")` is passed to `resolve_context_type`
- **THEN** it returns `ContextType.ORDER_LINE_SELECTION`

#### Scenario: ContextTypeResolver keeps agregar_producto on PRODUCT_SELECTION
- **WHEN** a ready `ProcessedIntent(intent="agregar_producto")` is passed to `resolve_context_type`
- **THEN** it returns `ContextType.PRODUCT_SELECTION`

### Requirement: Order-line selection resolver

The system SHALL expose `resolve_order_line_selection(db, session, message, active_intent) -> ProcessedIntent` from `backend/intents/context/order_line_selection_resolver.py`. The resolver SHALL use only the original or currently refined candidate IDs, refine them when the message matches a strict subset, return `ready` when one candidate remains (executing through the existing dispatcher), return `pending_resolution` otherwise, and reject any candidate ID not present in the current candidate set.

#### Scenario: Single refinement narrows candidates
- **WHEN** the active intent carries three pizza `pedido_producto_id` candidates and the new message is `la grande`
- **THEN** the resolver narrows `candidate_ids` to the two large-pizza lines and returns `pending_resolution` carrying the reduced set

#### Scenario: Refinement to one candidate returns ready
- **WHEN** the reduced set has exactly one `pedido_producto_id`
- **THEN** the resolver populates `resolved_data["pedido_producto_id"]`, sets `status="ready"`, and the existing ready-execution path runs `execute_quitar_producto` immediately

#### Scenario: Invalid candidate is rejected without mutation
- **WHEN** the message resolves to a `pedido_producto_id` not in the current candidate set
- **THEN** the resolver returns `rejected` without mutating the pedido

#### Scenario: Resolver does not broaden back to the catalog
- **WHEN** the message references a commerce product absent from the active candidate set
- **THEN** the resolver does not expand `candidate_ids` and returns either `pending_resolution` with the unreduced set or `rejected`

### Requirement: Orchestration boundaries

The initial orchestration and the order-line resolver SHALL NOT commit, rollback, flush, close, call FastAPI routers, import transport modules, perform SQLAlchemy queries outside the service layer, or generate customer-facing responses.

#### Scenario: Orchestration has no transaction side effects
- **WHEN** `process_initial_quitar_producto` or `resolve_order_line_selection` completes
- **THEN** `db.commit` and `db.rollback` have not been called by these modules

#### Scenario: Orchestration is free of HTTP and LLM imports
- **WHEN** the orchestration modules are imported
- **THEN** they do not import `requests`, `fastapi`, `backend.llm`, `backend.routers`, `backend.dependencies`, or `backend.old_project`

### Requirement: Public surface is limited

The initial orchestration module SHALL export only `process_initial_quitar_producto` through `__all__`. The order-line resolver module SHALL export only `resolve_order_line_selection` through `__all__`.

#### Scenario: Initial orchestration exports exactly one symbol
- **WHEN** the initial orchestration module's `__all__` is inspected
- **THEN** it equals `["process_initial_quitar_producto"]`

#### Scenario: Resolver exports exactly one symbol
- **WHEN** the resolver module's `__all__` is inspected
- **THEN** it equals `["resolve_order_line_selection"]`
