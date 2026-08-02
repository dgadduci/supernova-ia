# Capability: incoming-message-orchestrator

## Purpose

Provide a modern orchestrator `process_incoming_message(db, session, message) -> list[ProcessedIntent]` in `backend/intents/orchestration/incoming_message_orchestrator.py` that validates the inbound message, routes pending-context sessions to `dispatch_pending_context` and initial sessions to `dispatch_initial_message`, returns a list-shaped result preserving the dispatcher's order, and propagates dispatcher exceptions unchanged — without importing from `backend/old_project/`, performing SQLAlchemy queries, calling `commit()`/`rollback()`, or pulling in HTTP, FastAPI, Twilio, response-shaping, or queue modules.

## Requirements

### Requirement: Incoming message orchestrator module location

The system SHALL expose `process_incoming_message` from `backend/intents/orchestration/incoming_message_orchestrator.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Orchestrator is importable from the modern intents orchestration package

- **WHEN** a module executes `from backend.intents.orchestration.incoming_message_orchestrator import process_incoming_message`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Incoming message orchestrator signature

The system SHALL expose a single module-level function `process_incoming_message(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `process_incoming_message(db, session, "quiero una empanada")`
- **THEN** the orchestrator returns a `list[ProcessedIntent]` without raising

#### Scenario: Module exports only the orchestrator

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["process_incoming_message"]`

### Requirement: Message validation

The orchestrator SHALL validate `message` is a `str` and is non-empty after `strip()` before any dispatcher call. Non-string input SHALL raise `TypeError`; empty or whitespace-only input SHALL raise `ValueError`.

#### Scenario: Non-string message is rejected before dispatch

- **WHEN** `process_incoming_message(db, session, None)` or `process_incoming_message(db, session, 123)` is called
- **THEN** the function raises `TypeError` and neither `dispatch_pending_context` nor `dispatch_initial_message` is invoked

#### Scenario: Empty message is rejected before dispatch

- **WHEN** `process_incoming_message(db, session, "")` is called
- **THEN** the function raises `ValueError` and neither `dispatch_pending_context` nor `dispatch_initial_message` is invoked

#### Scenario: Whitespace-only message is rejected before dispatch

- **WHEN** `process_incoming_message(db, session, "   \n\t  ")` is called
- **THEN** the function raises `ValueError` and neither `dispatch_pending_context` nor `dispatch_initial_message` is invoked

### Requirement: Pending-context routing

When `session.context_type is not None`, the orchestrator SHALL call `dispatch_pending_context(db, session, message)` and SHALL return its result wrapped in a one-item list. The orchestrator SHALL NOT invoke `IntentClassifier` or `dispatch_initial_message` in this branch.

#### Scenario: Active product_selection context routes to dispatch_pending_context

- **WHEN** `session.context_type == "product_selection"` and `process_incoming_message(db, session, message)` is called
- **THEN** the function calls `dispatch_pending_context(db, session, message)` exactly once, does not call `dispatch_initial_message`, and returns a one-item list containing the `ProcessedIntent` returned by the pending-context dispatcher

#### Scenario: Any non-None context_type routes to dispatch_pending_context

- **WHEN** `session.context_type` is any non-`None` value and `process_incoming_message(db, session, message)` is called
- **THEN** the function routes to `dispatch_pending_context` regardless of the specific context value

#### Scenario: Pending-context dispatch errors propagate unchanged

- **WHEN** `dispatch_pending_context(db, session, message)` raises any exception
- **THEN** `process_incoming_message` re-raises the original exception without wrapping, converting to another type, or returning an empty list

### Requirement: Initial routing

When `session.context_type is None`, the orchestrator SHALL call `dispatch_initial_message(db, session, message)` and SHALL return its `list[ProcessedIntent]` unchanged, preserving the order produced by the classifier.

#### Scenario: None context_type routes to dispatch_initial_message

- **WHEN** `session.context_type is None` and `process_incoming_message(db, session, message)` is called
- **THEN** the function calls `dispatch_initial_message(db, session, message)` exactly once and returns its list unchanged

#### Scenario: Initial dispatch result order is preserved

- **WHEN** `dispatch_initial_message` returns a list of multiple `ProcessedIntent` items in classifier order
- **THEN** `process_incoming_message` returns the same items in the same order, including any mix of executed and rejected items

#### Scenario: Initial dispatch errors propagate unchanged

- **WHEN** `dispatch_initial_message(db, session, message)` raises `TypeError`, `ValueError`, `QueryLlmError`, or `pydantic.ValidationError`
- **THEN** `process_incoming_message` re-raises the original exception without wrapping, converting to another type, or returning an empty list

### Requirement: Pending result wrapping

When the pending-context branch runs, the orchestrator SHALL return `[dispatcher_result]` — a one-item list wrapping the single `ProcessedIntent` returned by `dispatch_pending_context` — and SHALL NOT flatten it to a bare `ProcessedIntent`.

#### Scenario: Pending result is wrapped in a one-item list

- **WHEN** `dispatch_pending_context` returns a single `ProcessedIntent`
- **THEN** `process_incoming_message` returns a `list` of length 1 whose only element is that `ProcessedIntent`

### Requirement: No persistence or transaction side effects

The orchestrator SHALL NOT execute SQLAlchemy queries, access repositories, call `commit()`, call `rollback()`, or generate a customer-facing response; persistence and commit/rollback remain the caller's responsibility.

#### Scenario: Orchestrator performs no SQLAlchemy query

- **WHEN** `process_incoming_message(db, session, message)` completes for any routing branch
- **THEN** no SQLAlchemy `select()`, `execute()`, `add()`, `delete()`, or relationship-loading call has been made by the orchestrator module

#### Scenario: Orchestrator does not commit or rollback

- **WHEN** `process_incoming_message(db, session, message)` completes
- **THEN** `db.commit` and `db.rollback` have not been called by the orchestrator module

### Requirement: No HTTP, FastAPI, Twilio, or response-generation imports

The orchestrator module SHALL NOT import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, or any handler / queue / response-shaping module and SHALL NOT format or shape customer-facing replies.

#### Scenario: Module is free of HTTP, FastAPI, Twilio, and response-generation imports

- **WHEN** `backend.intents.orchestration.incoming_message_orchestrator` is imported
- **THEN** it does not import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, or any handler / queue / response-shaping module

### Requirement: Public surface is limited

The orchestrator module SHALL export only `process_incoming_message` through `__all__` and SHALL NOT introduce additional helpers, classifiers, registries, handlers, or response objects.

#### Scenario: Only one public symbol is exported

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["process_incoming_message"]`

#### Scenario: Module has no additional public functions

- **WHEN** the orchestrator module is inspected for top-level `def` statements other than `process_incoming_message`
- **THEN** only `process_incoming_message` is defined (private constants and imports are permitted)

### Requirement: Incoming message orchestrator integration coverage

The integration test suite SHALL include a module `backend/tests/test_incoming_message_integration.py` that exercises `process_incoming_message` end-to-end against `supernova_test` with real orchestrators, recognizer, resolver, dispatcher, handler, and services. The suite SHALL mock only the external LLM classification boundary (`IntentClassifier.query`) and SHALL NOT mock any other internal component.

#### Scenario: Initial-message branch yields a pending product-selection context

- **WHEN** `process_incoming_message(db, session, "quiero 2 pizzas de mozzarella")` is invoked against a session with `session.context_type is None`, a freshly seeded commerce, client, draft pedido, and a product with two active presentations (`chica`, `grande`) and prices — with only `IntentClassifier.query` mocked to return one `agregar_producto` classified intent
- **THEN** the function returns exactly one `ProcessedIntent` whose `status == "pending_resolution"`; `session.context_type == "product_selection"`; the active pending intent is persisted on the session; and no `PedidoProducto` row exists

#### Scenario: Pending-context branch executes the order line

- **WHEN** `process_incoming_message(db, session, "la grande")` is invoked against the same session immediately after the initial-message branch has established an active `product_selection` pending context
- **THEN** `IntentClassifier` is not constructed; the function returns exactly one `ProcessedIntent` whose `status == "executed"`; exactly one `PedidoProducto` row exists with the `grande` presentation and `cantidad == 2`; `session.pending_intents` is empty; and `session.context_type is None`

### Requirement: Incoming pending-context outcomes are propagated without loss

When a session has active context, `process_incoming_message` SHALL return the complete `list[ProcessedIntent]` from `dispatch_pending_context` unchanged rather than wrapping or truncating it.

#### Scenario: One reply produces multiple executed additions

- **WHEN** pending dispatch resolves and executes multiple preserved `agregar_producto` intents
- **THEN** the incoming-message orchestrator returns every result once and in the same order

#### Scenario: One unresolved result remains one result

- **WHEN** pending dispatch returns a one-item `pending_resolution` list
- **THEN** the incoming-message orchestrator returns that same one-item list unchanged

### Requirement: Transactional processing remains one transaction per message

Propagating multiple outcomes SHALL NOT add commits or rollbacks to the incoming-message orchestrator; the transactional wrapper SHALL still commit exactly once after successful processing and roll back exactly once after a raised exception.

#### Scenario: Multiple outcomes commit once

- **WHEN** one resolution message executes multiple queued additions successfully
- **THEN** transactional processing commits once after all outcomes are produced

### Requirement: Incoming initial outcomes represent only work processed on that turn

For an initial message containing multiple `agregar_producto` items, the incoming-message orchestrator SHALL propagate the dispatcher's ordered outcomes unchanged and SHALL NOT expose queued inactive additions as responses.

#### Scenario: Initial HTTP turn exposes one clarification

- **WHEN** the initial message produces two ambiguous additions
- **THEN** the orchestrator returns exactly one `pending_resolution` outcome for the active first addition

#### Scenario: Ready work before ambiguity remains visible

- **WHEN** the initial message produces ready A followed by pending B
- **THEN** the orchestrator returns A `executed` then B `pending_resolution`

### Requirement: Incoming pending outcomes preserve promotion order

For a message routed to active pending context, the incoming-message orchestrator SHALL return the pending dispatcher's complete list unchanged, including a definitive active outcome followed by any automatically executed ready outcomes and at most one promoted clarification.

#### Scenario: Resolution response includes next clarification

- **WHEN** resolving active Carne promotes unresolved Pizza
- **THEN** the orchestrator returns Carne `executed` followed by Pizza `pending_resolution` without wrapping, truncating, reordering, or duplicating either item

### Requirement: Clarification-only messages bypass initial classification

While `session.context_type` identifies an active pending interaction, the incoming-message orchestrator SHALL route a clarification-only message to pending dispatch and SHALL NOT invoke the initial classifier for that message.

#### Scenario: Active-only clarification is not a new intent

- **WHEN** Carne is active with queued Pizza and the customer sends `picante`
- **THEN** the message resolves Carne through pending dispatch and is not classified as an independent intent

### Requirement: Multi-outcome processing remains one transaction per HTTP message

Sequential promotion SHALL preserve the existing transactional boundary: one successful incoming message commits once after all returned outcomes, and any raised exception causes one rollback with no false success response.

#### Scenario: Executed then promoted-ready success commits once

- **WHEN** one clarification executes the active addition and one or more promoted ready additions
- **THEN** the transactional wrapper commits exactly once after the complete ordered result is produced

#### Scenario: Later promotion exception rolls back the turn

- **WHEN** a later promoted handler raises after an earlier mutation in the same message
- **THEN** the transactional wrapper rolls back once and no customer response list is returned

### Requirement: Clarification-only resolution propagates all ordered advancement outcomes

While active pending context exists, the incoming-message orchestrator SHALL route the customer reply only to pending dispatch and SHALL return its complete ordered list unchanged. It SHALL NOT invoke initial classification, wrap the list again, truncate it, reorder it, or duplicate an outcome.

#### Scenario: Picante returns execution then promoted clarification

- **WHEN** `picante` resolves active Carne, executes it, and promotes unresolved Pizza
- **THEN** the orchestrator returns Carne `executed` first and Pizza `pending_resolution` second, exactly once each

#### Scenario: Picante bypasses initial classification

- **WHEN** Carne is active with queued Pizza and the incoming message is `picante`
- **THEN** the orchestrator calls pending dispatch and does not create or classify a new initial intent

### Requirement: Multi-outcome pending processing preserves one transaction per message

Returning an active definitive outcome and a promoted clarification SHALL NOT add transaction control to the incoming-message orchestrator. The transactional wrapper SHALL commit once after the complete successful result or roll back once when any internal step raises.

#### Scenario: Active execution and promotion commit once

- **WHEN** one clarification executes Carne and promotes Pizza without error
- **THEN** the complete ordered result is produced before the transactional wrapper commits exactly once

#### Scenario: Promotion failure returns no false success

- **WHEN** a later execution or promotion step raises after an earlier in-memory order mutation
- **THEN** the exception propagates and the transactional wrapper rolls back once without returning a partial response list

### Requirement: Incoming-message orchestrator accepts a diagnostic sink

The `process_incoming_message` function SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The function SHALL pass the sink through to the classifier call, the initial dispatcher, the pending-context dispatcher, and every resolver reachable through the dispatch path. The function SHALL NOT treat the sink as a return value; it SHALL NOT change the existing `list[ProcessedIntent]` return contract. The function SHALL NOT commit, rollback, flush, or perform any persistence operation. The function SHALL NOT change the dispatching behavior, the message validation, the pending-context routing, the initial routing, or the result wrapping.

#### Scenario: Default sink is a no-op
- **WHEN** `process_incoming_message(db, session, message)` is called without a `sink` argument
- **THEN** the orchestrator runs the same dispatch path as before, returns the same `list[ProcessedIntent]`, and emits no event

#### Scenario: Injected sink is propagated
- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` is called
- **THEN** the stub sink receives the classifier events and the resolver events emitted by the dispatch path, and the orchestrator still returns the same `list[ProcessedIntent]`

#### Scenario: Orchestrator does not commit or rollback
- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` completes for any routing branch
- **THEN** `db.commit` and `db.rollback` have not been called by the orchestrator module

### Requirement: Incoming-message orchestrator returns the sink's collected events

The `process_incoming_message` function SHALL NOT return the sink's events through its return value. The events are returned to the caller through the sink itself (`sink.events()`) and emitted by the FastAPI router as a `diagnostics` field on the response payload. The function's return contract SHALL remain `list[ProcessedIntent]`.

#### Scenario: Return type is unchanged
- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` is called with a sink that recorded events
- **THEN** the function returns a `list[ProcessedIntent]` (not a tuple, not a dict, not a `ProcessResult`) and the events are accessible through `sink.events()`

#### Scenario: Sink events are independent of the return value
- **WHEN** the orchestrator returns a `list[ProcessedIntent]` from the dispatch path
- **THEN** the same `list[ProcessedIntent]` is returned when the sink is a `NoopDiagnosticSink`, a `CollectingDiagnosticSink`, or any custom `DiagnosticSink` implementation