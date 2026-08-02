# Capability: incoming-message-transactional-processor

## Purpose

Provide a thin transactional wrapper around the incoming-message orchestrator that commits all returned business outcomes and rolls back then re-raises any exception, without duplicating orchestration, persistence, transport, response-generation, or retry behavior.

## Requirements

### Requirement: Transactional message processor module location

The system SHALL expose `process_incoming_message_transactional` from `backend/intents/orchestration/transactional_message_processor.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Transactional processor is importable from the modern intents orchestration package

- **WHEN** a module executes `from backend.intents.orchestration.transactional_message_processor import process_incoming_message_transactional`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Transactional message processor signature

The system SHALL expose a single module-level function `process_incoming_message_transactional(db: DatabaseSession, session: ConversationSession, message: str) -> list[ProcessedIntent]` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `process_incoming_message_transactional(db, session, "quiero una empanada")`
- **THEN** the function returns a `list[ProcessedIntent]` when no exception is raised by the inner call

#### Scenario: Module exports only the transactional processor

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["process_incoming_message_transactional"]`

### Requirement: Single delegation to the incoming-message orchestrator

The transactional processor SHALL call `process_incoming_message(db, session, message)` exactly once per invocation and SHALL NOT re-validate the message, re-route, or reshape the returned list.

#### Scenario: Inner orchestrator is called exactly once

- **WHEN** `process_incoming_message_transactional(db, session, message)` is invoked
- **THEN** `process_incoming_message(db, session, message)` is called exactly once with the same `db`, `session`, and `message` arguments

#### Scenario: Inner result is returned unchanged

- **WHEN** `process_incoming_message(db, session, message)` returns a `list[ProcessedIntent]` without raising
- **THEN** `process_incoming_message_transactional` returns that same list reference (the same `ProcessedIntent` items in the same order) once `db.commit()` has been called

### Requirement: Commit on success

The transactional processor SHALL call `db.commit()` exactly once when `process_incoming_message(db, session, message)` returns without raising, and SHALL NOT call `db.rollback()` in that branch.

#### Scenario: Successful processing commits exactly once

- **WHEN** `process_incoming_message(db, session, message)` returns a list of `ProcessedIntent` items without raising
- **THEN** `db.commit()` is called exactly once, `db.rollback()` is not called, and the returned list equals the inner orchestrator's return value

#### Scenario: Successful processing returns the inner result after commit

- **WHEN** `process_incoming_message(db, session, message)` returns a list and `db.commit()` completes
- **THEN** `process_incoming_message_transactional` returns that list to the caller

### Requirement: Rejected and failed results are committed business outcomes

The transactional processor SHALL treat `ProcessedIntent` items whose `status` is `"rejected"` or `"failed"` as valid business outcomes; the function SHALL commit exactly once when the inner orchestrator returns without raising, regardless of any per-item status.

#### Scenario: rejected result is committed

- **WHEN** `process_incoming_message(db, session, message)` returns a one-item list whose `ProcessedIntent.status == "rejected"` without raising
- **THEN** `db.commit()` is called exactly once, `db.rollback()` is not called, and the list is returned to the caller

#### Scenario: failed result is committed

- **WHEN** `process_incoming_message(db, session, message)` returns a one-item list whose `ProcessedIntent.status == "failed"` without raising
- **THEN** `db.commit()` is called exactly once, `db.rollback()` is not called, and the list is returned to the caller

#### Scenario: mixed-status list is committed atomically

- **WHEN** `process_incoming_message(db, session, message)` returns a multi-item list mixing `executed`, `rejected`, and `failed` items without raising
- **THEN** `db.commit()` is called exactly once, `db.rollback()` is not called, and the full list is returned to the caller

### Requirement: Rollback and re-raise on exception

The transactional processor SHALL call `db.rollback()` exactly once when `process_incoming_message(db, session, message)` raises any exception, and SHALL re-raise the original exception unchanged (no wrapping, no conversion, no swallowing). The transactional processor SHALL NOT call `db.commit()` in that branch.

#### Scenario: Exception triggers a single rollback

- **WHEN** `process_incoming_message(db, session, message)` raises any exception
- **THEN** `db.rollback()` is called exactly once, `db.commit()` is not called, and the exception propagates out of `process_incoming_message_transactional` unchanged

#### Scenario: Original exception type is preserved

- **WHEN** `process_incoming_message(db, session, message)` raises a `ValueError`, `TypeError`, `QueryLlmError`, `pydantic.ValidationError`, or any other exception
- **THEN** the same exception type and instance re-raise out of `process_incoming_message_transactional` (no wrapping, no conversion, no `HTTPException` translation)

#### Scenario: Original exception traceback is preserved

- **WHEN** `process_incoming_message(db, session, message)` raises an exception
- **THEN** the exception raised by `process_incoming_message_transactional` is the same Python object that was originally raised (identity-preserving or same `args` and same type), so the original traceback frames remain attached

### Requirement: No persistence, query, or repository side effects inside the wrapper

The transactional processor SHALL NOT execute SQLAlchemy `select()` / `execute()` / `add()` / `delete()`, SHALL NOT access repositories, and SHALL NOT call `db.flush()`, `db.refresh()`, `db.expire()`, or `db.begin()`; the only database session methods it invokes are `db.commit()` and `db.rollback()`.

#### Scenario: Wrapper performs no SQLAlchemy query

- **WHEN** `process_incoming_message_transactional(db, session, message)` is invoked
- **THEN** the wrapper itself has not executed any SQLAlchemy `select()`, `execute()`, `add()`, `delete()`, or relationship-loading call; the only database session calls are `db.commit()` (on success) or `db.rollback()` (on exception)

#### Scenario: Wrapper does not flush, refresh, or expire

- **WHEN** `process_incoming_message_transactional(db, session, message)` completes (success or exception)
- **THEN** `db.flush`, `db.refresh`, `db.expire`, and `db.begin` have not been called by the wrapper

### Requirement: No HTTP, FastAPI, Twilio, response-generation, or retry imports

The transactional processor module SHALL NOT import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, or any handler / queue / response-shaping module and SHALL NOT format or shape customer-facing replies, perform `HTTPException` translation, or implement retry/backoff/async wrappers.

#### Scenario: Module is free of HTTP, FastAPI, Twilio, and response-generation imports

- **WHEN** `backend.intents.orchestration.transactional_message_processor` is imported
- **THEN** it does not import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, or any handler / queue / response-shaping module

#### Scenario: Module does not perform HTTPException translation or retry

- **WHEN** `process_incoming_message_transactional(db, session, message)` is invoked
- **THEN** the wrapper does not catch and re-raise as `HTTPException`, does not catch and swallow the inner exception, does not retry the inner call, and does not introduce any backoff, caching, or async wrapper

### Requirement: Public surface is limited

The transactional processor module SHALL export only `process_incoming_message_transactional` through `__all__` and SHALL NOT introduce additional helpers, classifiers, registries, handlers, or response objects.

#### Scenario: Only one public symbol is exported

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["process_incoming_message_transactional"]`

#### Scenario: Module has no additional public functions

- **WHEN** the transactional processor module is inspected for top-level `def` statements other than `process_incoming_message_transactional`
- **THEN** only `process_incoming_message_transactional` is defined (private constants and imports are permitted)
