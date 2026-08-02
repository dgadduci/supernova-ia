## ADDED Requirements

### Requirement: Incoming message response orchestrator module location

The system SHALL expose `process_incoming_message_with_responses` from `backend/intents/orchestration/incoming_message_response_orchestrator.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Response orchestrator is importable from the modern intents orchestration package

- **WHEN** a module executes `from backend.intents.orchestration.incoming_message_response_orchestrator import process_incoming_message_with_responses`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Incoming message response orchestrator signature

The system SHALL expose a single module-level function `process_incoming_message_with_responses(db: DatabaseSession, session: ConversationSession, message: str) -> list[CustomerResponse]` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `process_incoming_message_with_responses(db, session, "quiero una empanada")`
- **THEN** the orchestrator returns a `list[CustomerResponse]` whose length matches the inner transactional processor's `list[ProcessedIntent]` return value

#### Scenario: Module exports only the response orchestrator

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["process_incoming_message_with_responses"]`

### Requirement: Single delegation to the transactional processor

The response orchestrator SHALL call `process_incoming_message_transactional(db, session, message)` exactly once per invocation and SHALL NOT re-validate the message, re-route, re-dispatch, or perform its own commit / rollback.

#### Scenario: Transactional processor is called exactly once

- **WHEN** `process_incoming_message_with_responses(db, session, message)` is invoked
- **THEN** `process_incoming_message_transactional(db, session, message)` is called exactly once with the same `db`, `session`, and `message` arguments

#### Scenario: Message validation is not duplicated

- **WHEN** `process_incoming_message_with_responses(db, session, "")` is invoked
- **THEN** the wrapper does not raise `ValueError` itself; the inner transactional processor raises `ValueError` and the exception propagates unchanged

### Requirement: Intent order preservation

The response orchestrator SHALL return one `CustomerResponse` per item in the inner transactional processor's `list[ProcessedIntent]` return value, in the same order, including any mix of executed, pending, rejected, and failed items.

#### Scenario: Multi-intent list preserves classifier order

- **WHEN** `process_incoming_message_transactional` returns a list of three `ProcessedIntent` items in the order `[pending_resolution, executed, rejected]`
- **THEN** `process_incoming_message_with_responses` returns a list of three `CustomerResponse` items in that same order, with the i-th `CustomerResponse` produced from the i-th `ProcessedIntent`

#### Scenario: Single-intent list has length 1

- **WHEN** `process_incoming_message_transactional` returns a one-item list
- **THEN** `process_incoming_message_with_responses` returns a one-item list

### Requirement: agregar_producto delegation

When a `ProcessedIntent.intent == "agregar_producto"`, the response orchestrator SHALL call `build_agregar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

#### Scenario: agregar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "executed"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "pending_resolution"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: agregar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "agregar_producto"` and `status == "failed"`
- **THEN** `build_agregar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

### Requirement: Unsupported intent generic response

When a `ProcessedIntent.intent` is anything other than `"agregar_producto"` (including `desconocida`, `saludo`, `quitar_producto`, `consultar_pedido`, or any future intent name), the response orchestrator SHALL append a deterministic generic `CustomerResponse` whose `message` is the module-level generic message, whose `intent` equals the original `ProcessedIntent.intent`, and whose `status` equals the original `ProcessedIntent.status`. The response orchestrator SHALL NOT invoke `build_agregar_producto_response` or any other response builder for that item.

#### Scenario: desconocida returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "desconocida"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response` is NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")`

#### Scenario: saludo returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "saludo"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response` is NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="saludo", status="rejected")`

#### Scenario: consultar_pedido returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "consultar_pedido"` and `status == "executed"`
- **THEN** `build_agregar_producto_response` is NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="consultar_pedido", status="executed")`

#### Scenario: Generic message is deterministic and free of technical detail

- **WHEN** the orchestrator builds the generic response for any unsupported intent
- **THEN** the resulting `CustomerResponse.message` equals the module-level generic constant, does NOT contain the literal string `"id"`, `"Exception"`, `"Traceback"`, or `"Error"`, and is a single fixed Spanish string with no per-call formatting

### Requirement: Exception propagation

When `process_incoming_message_transactional(db, session, message)` raises any exception, `process_incoming_message_with_responses` SHALL re-raise the original exception unchanged (no wrapping, no conversion, no swallowing, no `HTTPException` translation) and SHALL NOT construct any `CustomerResponse`.

#### Scenario: ValueError propagates unchanged

- **WHEN** `process_incoming_message_transactional(db, session, "")` raises `ValueError`
- **THEN** `process_incoming_message_with_responses` re-raises the same `ValueError` instance (or an instance with the same `args` and type), the original traceback frames remain attached, and no `CustomerResponse` is returned

#### Scenario: TypeError propagates unchanged

- **WHEN** `process_incoming_message_transactional(db, session, None)` raises `TypeError`
- **THEN** `process_incoming_message_with_responses` re-raises the same `TypeError` instance (or an instance with the same `args` and type)

#### Scenario: QueryLlmError propagates unchanged

- **WHEN** `process_incoming_message_transactional(db, session, message)` raises `QueryLlmError` (or any subclass)
- **THEN** `process_incoming_message_with_responses` re-raises the same exception instance

#### Scenario: pydantic ValidationError propagates unchanged

- **WHEN** `process_incoming_message_transactional(db, session, message)` raises `pydantic.ValidationError`
- **THEN** `process_incoming_message_with_responses` re-raises the same exception instance

### Requirement: No additional commit or rollback

The response orchestrator SHALL NOT call `db.commit()`, `db.rollback()`, `db.flush()`, `db.refresh()`, `db.expire()`, or `db.begin()`. Transaction ownership remains exclusively with `process_incoming_message_transactional`.

#### Scenario: No commit on success

- **WHEN** `process_incoming_message_with_responses(db, session, message)` returns normally
- **THEN** `db.commit` has not been called by the response orchestrator module

#### Scenario: No rollback on exception

- **WHEN** `process_incoming_message_with_responses(db, session, message)` raises an exception
- **THEN** `db.rollback` has not been called by the response orchestrator module

### Requirement: No SQLAlchemy query or repository access

The response orchestrator SHALL NOT execute SQLAlchemy `select()` / `execute()` / `add()` / `delete()`, SHALL NOT load relationships, and SHALL NOT import `sqlalchemy.select`, `sqlalchemy.orm.joinedload`, `backend.repositories.*`, or `backend.services.*`. All database access is delegated to the inner transactional processor and to `build_agregar_producto_response`.

#### Scenario: Module performs no direct SQLAlchemy query

- **WHEN** `process_incoming_message_with_responses(db, session, message)` completes for any routing branch
- **THEN** no SQLAlchemy `select()`, `execute()`, `add()`, `delete()`, or relationship-loading call has been made by the response orchestrator module

#### Scenario: Module imports no repository or service

- **WHEN** the response orchestrator module is imported
- **THEN** it does not import `backend.repositories.*`, `backend.services.*`, `backend.intents.handlers.*`, `backend.intents.context.*`, `backend.intents.recognizers.*`, `backend.intents.resolvers.*`, `backend.intents.processor`, `backend.intents.contracts.*`, or `backend.intents.services.*`

### Requirement: No HTTP, FastAPI, Twilio, LLM, or response-generation imports

The response orchestrator module SHALL NOT import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, `backend.dependencies`, `backend.llm`, or `backend.old_project`, and SHALL NOT format or shape customer-facing replies beyond the delegation to `build_agregar_producto_response` and the module-level generic constant.

#### Scenario: Module is free of HTTP, FastAPI, Twilio, LLM, and transport imports

- **WHEN** `backend.intents.orchestration.incoming_message_response_orchestrator` is imported
- **THEN** it does not import `requests`, `fastapi`, `twilio`, `backend.routers`, `backend.sessions`, `backend.dependencies`, `backend.llm`, or `backend.old_project`

#### Scenario: Module contains no HTTPException or MessagingResponse

- **WHEN** the response orchestrator module source is inspected
- **THEN** it contains no `HTTPException`, `Response(`, `JSONResponse(`, `MessagingResponse`, `Client(`, or `QueryLlm` reference

### Requirement: No mutation, no logging, no retry, no async, no queue

The response orchestrator SHALL NOT mutate `session`, any `ProcessedIntent`, any `CustomerResponse` it has already appended, or any model attribute; SHALL NOT introduce logging, retry / backoff, async wrappers, or caching; and SHALL NOT import any queue module.

#### Scenario: Module does not mutate session or intent

- **WHEN** `process_incoming_message_with_responses(db, session, message)` is invoked for any routing branch
- **THEN** `session.pending_intents`, `session.context_type`, `session.id_pedido`, and every field of every input `ProcessedIntent` equal the values they had before the call

#### Scenario: Module does not log, retry, or go async

- **WHEN** the response orchestrator module source is inspected
- **THEN** it does not call `logging.`, `logger.`, `print(`, `time.sleep`, `asyncio`, `await`, `retry`, or `backoff`

### Requirement: Public surface is limited

The response orchestrator module SHALL export only `process_incoming_message_with_responses` through `__all__` and SHALL NOT introduce additional helpers, registries, factories, multi-intent dispatchers, or response objects for new intents.

#### Scenario: Only one public symbol is exported

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["process_incoming_message_with_responses"]`

#### Scenario: Module has no additional public functions

- **WHEN** the response orchestrator module is inspected for top-level `def` statements other than `process_incoming_message_with_responses`
- **THEN** only `process_incoming_message_with_responses` is defined (private constants and imports are permitted)