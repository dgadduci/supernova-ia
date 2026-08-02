## ADDED Requirements

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
