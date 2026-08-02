## ADDED Requirements

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

### Requirement: desconocida rejection

When the classifier returns a `ClassifiedIntent(intent=IntentName.DESCONOCIDA, mensaje=...)`, the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent="desconocida"`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler="desconocida"`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: desconocida produces a rejected ProcessedIntent

- **WHEN** the classifier returns one `ClassifiedIntent(intent=DESCONOCIDA, mensaje="asdfgh")`
- **THEN** `process_initial_agregar_producto` is not invoked and the returned list contains a single `ProcessedIntent(intent="desconocida", source_text="asdfgh", status="rejected", recognizer="intent_classifier", handler="desconocida", resolved_data={}, requirements=[], candidate_ids=[])`

### Requirement: Unsupported intent rejection

When the classifier returns a `ClassifiedIntent(intent=...)` for any `IntentName` other than `AGREGAR_PRODUCTO` (and not `DESCONOCIDA`, which has its own rule), the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent=<intent string>`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler=<intent string>`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: saludo is rejected without execution

- **WHEN** the classifier returns one `ClassifiedIntent(intent=SALUDO, mensaje="hola")`
- **THEN** `process_initial_agregar_producto` is not invoked and the returned list contains a single `ProcessedIntent(intent="saludo", source_text="hola", status="rejected", recognizer="intent_classifier", handler="saludo", resolved_data={}, requirements=[], candidate_ids=[])`

#### Scenario: quitar_producto is rejected without execution

- **WHEN** the classifier returns one `ClassifiedIntent(intent=QUITAR_PRODUCTO, mensaje="quita la empanada")`
- **THEN** `process_initial_agregar_producto` is not invoked and the returned list contains a `ProcessedIntent` with `status="rejected"` carrying `intent="quitar_producto"` and `handler="quitar_producto"`

#### Scenario: Unknown intent names are not raised here

- **WHEN** the classifier returns a `ClassifiedIntent` with an `IntentName` that has no supported branch in the dispatcher
- **THEN** the dispatcher returns a `rejected` `ProcessedIntent` for that item instead of raising

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
