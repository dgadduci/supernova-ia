# Initial Intent Dispatcher Specification

## Purpose

Provide the top-level entry point `dispatch_initial_message` that classifies a first user message, delegates recognized intents to the appropriate orchestrator, and emits one `ProcessedIntent` per classified item — without owning persistence, transactions, HTTP, or response generation.
## Requirements
### Requirement: Initial intent dispatcher module location
The system SHALL expose `dispatch_initial_message` from `backend/intents/orchestration/initial_intent_dispatcher.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Dispatcher is importable from the modern intents orchestration package
- **WHEN** a module executes `from backend.intents.orchestration.initial_intent_dispatcher import dispatch_initial_message`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Initial intent dispatcher signature
The system SHALL expose a single module-level function `dispatch_initial_message(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` aliased via `typing` exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature
- **WHEN** a caller invokes `dispatch_initial_message(db, session, "quiero una empanada")`
- **THEN** the dispatcher returns a `list[ProcessedIntent]` (possibly empty) without raising

#### Scenario: Module exports only the dispatcher
- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["dispatch_initial_message"]`

### Requirement: Pending-context short-circuit
The dispatcher SHALL return an empty list and SHALL NOT invoke `IntentClassifier`, `process_initial_agregar_producto`, or any other orchestrator when `session.context_type is not None`.

#### Scenario: Active product_selection context prevents initial dispatch
- **WHEN** `session.context_type == "product_selection"` and `dispatch_initial_message(db, session, message)` is called
- **THEN** the function returns `[]` and the classifier is never constructed

#### Scenario: Any non-None context_type prevents initial dispatch
- **WHEN** `session.context_type` is any non-`None` value and `dispatch_initial_message(db, session, message)` is called
- **THEN** the function returns `[]` regardless of message content

#### Scenario: None context allows classification
- **WHEN** `session.context_type is None` and `dispatch_initial_message(db, session, message)` is called
- **THEN** the classifier is invoked and a non-empty list (or whatever the classifier produced) is returned

### Requirement: IntentClassifier delegation
The dispatcher SHALL construct an `IntentClassifier`, call `query(message)` exactly once, and SHALL propagate `TypeError`, `ValueError`, `QueryLlmError`, and `pydantic.ValidationError` unchanged — no printing, no swallowing, no wrapping, no `None` returns.

#### Scenario: Classifier is invoked exactly once
- **WHEN** `dispatch_initial_message(db, session, message)` proceeds past the pending-context guard
- **THEN** `IntentClassifier().query(message)` is called exactly once with the same `message` string

#### Scenario: Classifier errors propagate unchanged
- **WHEN** `IntentClassifier.query(message)` raises `TypeError`, `ValueError`, `QueryLlmError`, or `pydantic.ValidationError`
- **THEN** `dispatch_initial_message` re-raises the original exception without wrapping, converting to another type, or returning `None`

### Requirement: agregar_producto dispatch
When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_agregar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list.

#### Scenario: agregar_producto returns the orchestrator's ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=AGREGAR_PRODUCTO, mensaje="una empanada")`
- **THEN** `dispatch_initial_message` calls `process_initial_agregar_producto(db, session, "una empanada")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: agregar_producto alongside other intents preserves order
- **WHEN** the classifier returns `agregar_producto` then `desconocida`
- **THEN** the returned list contains the `agregar_producto` orchestrator result in position 0 and the `desconocida` rejected `ProcessedIntent` in position 1, in that order

### Requirement: quitar_producto dispatch
When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.QUITAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_quitar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list. The orchestrator's returned `status` (`ready`, `pending_resolution`, `rejected`, `failed`) SHALL be propagated unchanged.

#### Scenario: quitar_producto returns the orchestrator's ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=QUITAR_PRODUCTO, mensaje="quitá la pizza de muzzarella grande")`
- **THEN** `dispatch_initial_message` calls `process_initial_quitar_producto(db, session, "quitá la pizza de muzzarella grande")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: quitar_producto preserves orchestrator status
- **WHEN** `process_initial_quitar_producto` returns a `ProcessedIntent(status="ready")` for a unique match
- **THEN** `dispatch_initial_message` returns that intent unchanged and does NOT auto-execute the handler

#### Scenario: quitar_producto pending_resolution is preserved
- **WHEN** `process_initial_quitar_producto` returns a `ProcessedIntent(status="pending_resolution", context_type="order_line_selection")`
- **THEN** `dispatch_initial_message` returns that intent unchanged

### Requirement: desconocida rejection
When the classifier returns a `ClassifiedIntent(intent=IntentName.DESCONOCIDA, mensaje=...)`, the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent="desconocida"`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler="desconocida"`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: desconocida produces a rejected ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=DESCONOCIDA, mensaje="asdfgh")`
- **THEN** `process_initial_agregar_producto` is not invoked and the returned list contains a single `ProcessedIntent(intent="desconocida", source_text="asdfgh", status="rejected", recognizer="intent_classifier", handler="desconocida", resolved_data={}, requirements=[], candidate_ids=[])`

### Requirement: Unsupported intent rejection
When the classifier returns a `ClassifiedIntent(intent=...)` for any `IntentName` other than `AGREGAR_PRODUCTO`, `QUITAR_PRODUCTO`, or `MODIFICAR_PRODUCTO` (and not `DESCONOCIDA`, which has its own rule), the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent=<intent string>`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler=<intent string>`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: saludo is rejected without execution
- **WHEN** the classifier returns one `ClassifiedIntent(intent=SALUDO, mensaje="hola")`
- **THEN** `process_initial_agregar_producto`, `process_initial_quitar_producto`, and `process_initial_modificar_producto` are not invoked and the returned list contains a single `ProcessedIntent(intent="saludo", source_text="hola", status="rejected", recognizer="intent_classifier", handler="saludo", resolved_data={}, requirements=[], candidate_ids=[])`

#### Scenario: Unknown intent names are not raised here
- **WHEN** the classifier returns a `ClassifiedIntent` with an `IntentName` that has no supported branch in the dispatcher
- **THEN** the dispatcher returns a `rejected` `ProcessedIntent` for that item instead of raising

### Requirement: modificar_producto dispatch
When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.MODIFICAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_modificar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list. The orchestrator's returned `status` (`ready`, `pending_resolution`, `rejected`, `failed`) SHALL be propagated unchanged.

#### Scenario: modificar_producto returns the orchestrator's ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=MODIFICAR_PRODUCTO, mensaje="cambiá la pizza de muzzarella chica por una grande")`
- **THEN** `dispatch_initial_message` calls `process_initial_modificar_producto(db, session, "cambiá la pizza de muzzarella chica por una grande")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: modificar_producto preserves orchestrator status
- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="ready")` for unique source and destination matches
- **THEN** `dispatch_initial_message` returns that intent unchanged and does NOT auto-execute the handler

#### Scenario: modificar_producto pending_resolution is preserved
- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="pending_resolution", context_type="product_modification")`
- **THEN** `dispatch_initial_message` returns that intent unchanged

#### Scenario: modificar_producto rejected is preserved
- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="rejected")` for an absent source, an unavailable destination, or an equivalent source-and-destination case
- **THEN** `dispatch_initial_message` returns that intent unchanged

#### Scenario: modificar_producto does not invoke other orchestrators
- **WHEN** the classifier returns one `ClassifiedIntent(intent=MODIFICAR_PRODUCTO, mensaje="...")`
- **THEN** `process_initial_agregar_producto` and `process_initial_quitar_producto` are NOT invoked

### Requirement: Order preservation across multiple intents
The dispatcher SHALL return one `ProcessedIntent` per classified item, in the same order as `IntentClassificationResult.intents`, including any mix of executed and rejected items.

#### Scenario: Mixed classified intents preserve order
- **WHEN** the classifier returns three `ClassifiedIntent` items in the order `AGREGAR_PRODUCTO`, `DESCONOCIDA`, `SALUDO`
- **THEN** the returned list has length 3, in that exact order, with the `agregar_producto` slot populated by the orchestrator's result and the other two slots populated by rejected `ProcessedIntent` values

#### Scenario: Single-intent list has length 1
- **WHEN** the classifier returns a list of one `ClassifiedIntent`
- **THEN** the dispatcher returns a list of length 1 with the corresponding `ProcessedIntent`

### Requirement: No persistence or transaction side effects
The dispatcher SHALL NOT execute SQLAlchemy queries, access repositories, call `commit()`, call `rollback()`, or generate a customer-facing response; persistence and commit/rollback remain the caller's responsibility.

#### Scenario: Dispatcher performs no SQLAlchemy query
- **WHEN** `dispatch_initial_message(db, session, message)` completes for any supported or rejected branch
- **THEN** no SQLAlchemy `select()`, `execute()`, `add()`, `delete()`, or relationship-loading call has been made by the dispatcher module

#### Scenario: Dispatcher does not commit or rollback
- **WHEN** `dispatch_initial_message(db, session, message)` completes
- **THEN** `db.commit` and `db.rollback` have not been called by the dispatcher module

### Requirement: No HTTP, FastAPI, or response-generation imports
The dispatcher module SHALL NOT import `requests`, `fastapi`, `backend.routers`, or `backend.sessions` and SHALL NOT format or shape customer-facing replies.

#### Scenario: Module is free of HTTP and FastAPI imports
- **WHEN** `backend.intents.orchestration.initial_intent_dispatcher` is imported
- **THEN** it does not import `requests`, `fastapi`, `backend.routers`, or `backend.sessions` (the latter contains session-context helpers, not the conversation `Session` model)

### Requirement: Public surface is limited
The dispatcher module SHALL export only `dispatch_initial_message` through `__all__` and SHALL NOT introduce additional helpers, classifiers, registries, handlers, or response objects.

#### Scenario: Only one public symbol is exported
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["dispatch_initial_message"]`

#### Scenario: Module has no additional public functions
- **WHEN** the dispatcher module is inspected for top-level `def` statements other than `dispatch_initial_message`
- **THEN** only `dispatch_initial_message` is defined (private constants and imports are permitted)

### Requirement: Multiple agregar_producto classifications enter one ordered pending lifecycle
The dispatcher SHALL preserve every `agregar_producto` result from the classifier in classifier order. If any addition requires product resolution, the first unresolved addition SHALL be active and all later additions that remain to be processed SHALL be retained in the FIFO pending queue without replacing an earlier active item.

#### Scenario: Two ambiguous additions are both retained
- **WHEN** the classifier returns two `agregar_producto` items and both initial orchestrator calls return `pending_resolution`
- **THEN** the returned results retain classifier order, the first is active, and the second is queued

#### Scenario: Pending then ready addition is retained
- **WHEN** the first classified addition is pending and the second is ready
- **THEN** the pending addition is active and the ready addition is queued for execution after resolution

#### Scenario: Ready then pending addition preserves order
- **WHEN** the first classified addition is ready and the second is pending
- **THEN** both additions remain represented in classifier order and the ready addition executes before the unresolved addition becomes the active clarification target

### Requirement: Non-agregar dispatcher behavior remains unchanged
The batch-preservation behavior SHALL apply only to `agregar_producto`; existing dispatch and rejection behavior for all other intent names SHALL remain unchanged.

#### Scenario: Other intent types are not inserted into product-selection queue
- **WHEN** a classifier result mixes `agregar_producto` with `quitar_producto`, `modificar_producto`, or an unsupported intent
- **THEN** the dispatcher SHALL NOT enqueue those other intents as product-selection work

### Requirement: Initial agregar_producto results stop at the active interaction boundary
When one classification contains multiple `agregar_producto` items, the dispatcher SHALL process them in classifier/source order. It SHALL return immediate outcomes only through the first `pending_resolution` item and SHALL NOT return later queued additions as customer-visible outcomes on that turn.

#### Scenario: Two ambiguous additions expose only the first clarification
- **WHEN** one message produces pending additions for Carne and then Pizza
- **THEN** Carne is active, Pizza is queued, and the returned list contains only the Carne `pending_resolution` result

#### Scenario: Ready before pending executes before clarification
- **WHEN** classified additions are ready A followed by pending B
- **THEN** A executes, B becomes active, and the returned results are A `executed` followed by B `pending_resolution`

#### Scenario: Pending before ready pauses interaction
- **WHEN** classified additions are pending A followed by ready B
- **THEN** A becomes active, B is queued, and the returned list contains only A `pending_resolution`

### Requirement: Initial queue preserves all work after the first unresolved addition
After the first pending `agregar_producto` becomes active, the dispatcher SHALL retain every later `agregar_producto` as its complete persisted `ProcessedIntent` in FIFO source order, whether its current status is `ready` or `pending_resolution`.

#### Scenario: Pending ready pending order is persisted
- **WHEN** classified additions are pending A, ready B, and pending C
- **THEN** A is active and the queue contains B then C with their original statuses and values

#### Scenario: Queued intent data is unchanged
- **WHEN** an ambiguous queued addition has source text, quantity, candidate IDs, resolved data, requirements, handler, intent name, and refinement state
- **THEN** all those values are persisted unchanged and are not reconstructed from customer-facing text

### Requirement: Initial queue behavior remains agregar_producto-specific
The dispatcher SHALL NOT place unrelated `quitar_producto`, `modificar_producto`, or unsupported intents into the `product_selection` queue as part of this sequential-addition behavior.

#### Scenario: Other intents are not inserted behind an addition
- **WHEN** classification contains an `agregar_producto` pending item followed by another intent type
- **THEN** the other intent is not persisted as `product_selection` queue work

### Requirement: Explicit iniciar_pedido dispatch is session-safe

When the classifier returns `INICIAR_PEDIDO` and the active session has no pending context, the initial dispatcher SHALL delegate the classified message to the approved new-order transition. It SHALL preserve the existing rejection behavior for all unsupported intents and SHALL NOT invoke the transition for any other intent.

#### Scenario: Explicit new-order intent reaches the transition

- **WHEN** the classifier returns one `ClassifiedIntent(intent=INICIAR_PEDIDO, mensaje="quiero hacer otro pedido")`
- **THEN** the dispatcher calls the new-order transition once with the supplied database session, conversation session, and classified message
- **AND** returns that transition's `ProcessedIntent`

### Requirement: Successful session replacement ends the current turn

After `iniciar_pedido` successfully creates a successor session/order, the dispatcher SHALL NOT dispatch later classified intents from that same inbound message against the closed predecessor session.

#### Scenario: Later product intent is not applied to the closed order

- **WHEN** the classifier returns `iniciar_pedido` followed by `agregar_producto`
- **AND** the new-order transition succeeds
- **THEN** the dispatcher returns only the successor transition result for that boundary
- **AND** it does not call the product orchestrator with the closed predecessor session
