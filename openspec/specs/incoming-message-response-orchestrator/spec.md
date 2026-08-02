# Capability: incoming-message-response-orchestrator

## Purpose

Provide a thin response-layer wrapper around the transactional message processor that converts each returned `ProcessedIntent` into a `CustomerResponse` (delegating `agregar_producto` to `build_agregar_producto_response` and producing a deterministic generic response for every other intent), without re-validating input, re-running orchestration, owning transactions, performing SQLAlchemy access, importing transport / LLM / queue modules, mutating state, or introducing logging, retry, or async behavior.

## Requirements

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

### Requirement: quitar_producto delegation

When a `ProcessedIntent.intent == "quitar_producto"`, the response orchestrator SHALL call `build_quitar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

#### Scenario: quitar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "executed"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "pending_resolution"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "rejected"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: quitar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "quitar_producto"` and `status == "failed"`
- **THEN** `build_quitar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

### Requirement: Unsupported intent generic response

When a `ProcessedIntent.intent` is anything other than `"agregar_producto"`, `"quitar_producto"`, or `"modificar_producto"` (including `desconocida`, `saludo`, `consultar_pedido`, or any future intent name), the response orchestrator SHALL append a deterministic generic `CustomerResponse` whose `message` is the module-level generic message, whose `intent` equals the original `ProcessedIntent.intent`, and whose `status` equals the original `ProcessedIntent.status`. The response orchestrator SHALL NOT invoke `build_agregar_producto_response`, `build_quitar_producto_response`, `build_modificar_producto_response`, or any other response builder for that item.

#### Scenario: desconocida returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "desconocida"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")`

#### Scenario: saludo returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "saludo"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="saludo", status="rejected")`

#### Scenario: consultar_pedido returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "consultar_pedido"` and `status == "executed"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="consultar_pedido", status="executed")`

#### Scenario: Generic message is deterministic and free of technical detail

- **WHEN** the orchestrator builds the generic response for any unsupported intent
- **THEN** the resulting `CustomerResponse.message` equals the module-level generic constant, does NOT contain the literal string `"id"`, `"Exception"`, `"Traceback"`, or `"Error"`, and is a single fixed Spanish string with no per-call formatting

### Requirement: Unsupported intent generic response excludes modificar_producto

When a `ProcessedIntent.intent` is anything other than `"agregar_producto"`, `"quitar_producto"`, or `"modificar_producto"` (including `desconocida`, `saludo`, `consultar_pedido`, or any future intent name), the response orchestrator SHALL append a deterministic generic `CustomerResponse`. The response orchestrator SHALL NOT invoke `build_agregar_producto_response`, `build_quitar_producto_response`, `build_modificar_producto_response`, or any other response builder for that item.

#### Scenario: desconocida returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "desconocida"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")`

#### Scenario: saludo returns the generic CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "saludo"` and `status == "rejected"`
- **THEN** `build_agregar_producto_response`, `build_quitar_producto_response`, and `build_modificar_producto_response` are NOT invoked and the orchestrator returns a one-item list containing a `CustomerResponse(message=GENERIC_MESSAGE, intent="saludo", status="rejected")`

### Requirement: modificar_producto delegation

When a `ProcessedIntent.intent == "modificar_producto"`, the response orchestrator SHALL call `build_modificar_producto_response(db, session, intent)` exactly once, append the returned `CustomerResponse` to the output list, and SHALL NOT construct any other `CustomerResponse` for that item.

#### Scenario: modificar_producto returns the builder's CustomerResponse

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "executed"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once with the same `db`, `session`, and `intent`, and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with pending_resolution routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "pending_resolution"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with rejected routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "rejected"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto with failed routes to the builder

- **WHEN** `process_incoming_message_transactional` returns a one-item list whose `ProcessedIntent.intent == "modificar_producto"` and `status == "failed"`
- **THEN** `build_modificar_producto_response(db, session, intent)` is called exactly once and the orchestrator returns a one-item list containing the builder's returned `CustomerResponse`

#### Scenario: modificar_producto does not invoke other response builders

- **WHEN** the orchestrator handles a `modificar_producto` item
- **THEN** `build_agregar_producto_response` and `build_quitar_producto_response` are NOT invoked

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

### Requirement: Local HTTP seam for the incoming message response orchestrator

The system SHALL expose a single local HTTP seam — `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`, defined in `backend/routers/incoming_messages.py` — that accepts an inbound message, resolves the active conversation through `SessionService.get_active(comercio_id, cliente_id)`, and delegates to `process_incoming_message_with_responses(db, session, message)`. The seam exists so any local caller (test harness, future Twilio adapter, queue worker, integration test) can reach the modern pipeline through one obvious HTTP entry point instead of hand-wiring the orchestrator and shaping JSON themselves. The seam SHALL NOT introduce a new orchestrator, a new transactional wrapper, or a new response builder; it SHALL only route HTTP into the existing `process_incoming_message_with_responses` and the resulting `list[CustomerResponse]` back out through the `IncomingMessageResponse` envelope.

#### Scenario: Local HTTP seam is reachable from a FastAPI TestClient

- **WHEN** a `fastapi.testclient.TestClient` instance is constructed against a fresh `FastAPI()` app that includes the `incoming_messages.router` and overrides `get_session` with a stubbed session
- **THEN** a `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` request with a valid JSON body returns HTTP 200 and the response body is an `IncomingMessageResponse` whose `responses` field equals the list returned by `process_incoming_message_with_responses`

#### Scenario: Local HTTP seam delegates to the response orchestrator exactly once

- **WHEN** the endpoint handles a valid request
- **THEN** `process_incoming_message_with_responses` is called exactly once with `(db, session, payload.message)`; the orchestrator's behavior, the transactional wrapper's commit / rollback boundary, and the per-intent dispatch rules remain unchanged

#### Scenario: Local HTTP seam translates the documented exceptions

- **WHEN** the response orchestrator (or `SessionService.get_active`) raises `SessionNotFound`, `TypeError`, or `ValueError`
- **THEN** the seam translates them to HTTP 404 (`SessionNotFound`), HTTP 400 (`TypeError`), or HTTP 400 (`ValueError`); any other exception propagates unchanged so FastAPI's default handler turns it into HTTP 500 without the seam swallowing context

#### Scenario: Local HTTP seam is the documented entry point for the modern pipeline

- **WHEN** the `incoming-message-response-orchestrator` capability is referenced from a future Twilio / queue / webhook adapter
- **THEN** the adapter SHALL consume the seam at `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` (or, for adapters that cannot speak HTTP, `process_incoming_message_with_responses` directly) and SHALL NOT bypass the seam by calling `process_incoming_message`, `process_incoming_message_transactional`, or any inner dispatcher / handler / recognizer / resolver / processor / service / repository

#### Scenario: Local HTTP seam does not introduce logging, retry, async, or queue promotion

- **WHEN** the seam source is inspected
- **THEN** it contains no `logging.`, no `logger.`, no `print(`, no `time.sleep`, no `asyncio`, no `await`, no `async def`, no `retry`, no `backoff`, and no import from any queue module; all transport concerns remain the responsibility of the future adapters that consume the seam
