# Capability: incoming-messages-local-http-endpoint

## Purpose

Expose the modern incoming-message response pipeline through one local synchronous HTTP endpoint without adding transport, transaction, repository, LLM, retry, logging, or asynchronous behavior.

## Requirements

### Requirement: Incoming message local HTTP endpoint module location

The system SHALL expose the local HTTP endpoint from `backend/routers/incoming_messages.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Incoming messages router is importable

- **WHEN** a module executes `from backend.routers.incoming_messages import router`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Incoming message local HTTP endpoint route

The router SHALL expose exactly one route: `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`. The route SHALL accept the path parameters `comercio_id: int` and `cliente_id: int`, the JSON request body `IncomingMessageRequest`, the SQLAlchemy session via the existing `get_session` dependency, and the `SessionService` via a small `Depends` factory that wraps `get_session`. The route SHALL NOT add any additional path.

#### Scenario: Endpoint is registered at the documented path

- **WHEN** the FastAPI app from `backend/main.py` is inspected for routes
- **THEN** exactly one route with `path == "/comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages"` and `methods` containing `"POST"` is registered

#### Scenario: Endpoint is wired into the main app

- **WHEN** `backend/main.py` is inspected
- **THEN** it imports `incoming_messages` from `backend.routers` and calls `app.include_router(incoming_messages.router)` exactly once

### Requirement: Incoming message request and response schemas

The system SHALL expose `IncomingMessageRequest` and `IncomingMessageResponse` from `backend/schemas/incoming_message.py`. `IncomingMessageRequest` SHALL be a Pydantic `BaseModel` with exactly one field `message: str`, declared with `model_config = ConfigDict(extra="forbid")`. `IncomingMessageResponse` SHALL be a Pydantic `BaseModel` with exactly one field `responses: list[CustomerResponse]`, declared with `model_config = ConfigDict(from_attributes=True)`. The module SHALL export only `IncomingMessageRequest` and `IncomingMessageResponse` through `__all__`.

#### Scenario: Request schema accepts a non-empty string message

- **WHEN** a caller constructs `IncomingMessageRequest(message="quiero una empanada")`
- **THEN** the resulting model exposes `message == "quiero una empanada"`

#### Scenario: Request schema rejects non-string messages

- **WHEN** a caller constructs `IncomingMessageRequest(message=None)` or `IncomingMessageRequest(message=123)`
- **THEN** Pydantic raises `pydantic.ValidationError` before the route handler runs

#### Scenario: Request schema rejects extra fields

- **WHEN** the request JSON contains a key other than `message`
- **THEN** Pydantic raises `pydantic.ValidationError` and FastAPI returns HTTP 422

#### Scenario: Response schema wraps the customer response list

- **WHEN** the handler builds `IncomingMessageResponse(responses=[CustomerResponse(message="Listo", intent="agregar_producto", status="executed")])`
- **THEN** the resulting model exposes `responses` as a list whose only element is the supplied `CustomerResponse`

#### Scenario: Schemas module exports only the two models

- **WHEN** `backend.schemas.incoming_message` is imported and `__all__` is inspected
- **THEN** `__all__` equals `["IncomingMessageRequest", "IncomingMessageResponse"]`

### Requirement: Active session resolution through SessionService

The route handler SHALL resolve the active conversation through `SessionService.get_active(comercio_id, cliente_id)` exactly once per request and SHALL NOT issue its own SQLAlchemy query against the `sessions` table.

#### Scenario: get_active is called with the documented arguments

- **WHEN** the handler runs with `comercio_id` and `cliente_id` from the path and the JSON body `{"message": "quiero una pizza"}`
- **THEN** `SessionService.get_active` is called exactly once with `(comercio_id, cliente_id)` in that order

#### Scenario: Missing active session returns HTTP 404

- **WHEN** `SessionService.get_active(comercio_id, cliente_id)` raises `SessionNotFound`
- **THEN** the handler raises `HTTPException(status_code=404, detail=str(exc))` chained from the original exception, and the route returns HTTP 404 with that detail string in the JSON body

#### Scenario: Handler does not query the sessions table directly

- **WHEN** the router module source is inspected
- **THEN** it does not import `sqlalchemy.select`, `backend.repositories.session_repository`, or any direct SQLAlchemy ORM query against `Session`

### Requirement: Single delegation to the modern response orchestrator

The route handler SHALL call `process_incoming_message_with_responses(db, session, message)` exactly once per request and SHALL NOT re-validate the message, re-route on `session.context_type`, or invoke the transactional processor directly.

#### Scenario: Response orchestrator is called with the documented arguments

- **WHEN** the handler has resolved `session` and parsed `payload.message` and the inner call returns successfully
- **THEN** `process_incoming_message_with_responses` is called exactly once with `(db, session, payload.message)`

#### Scenario: Response orchestrator exceptions propagate unchanged for non-translated types

- **WHEN** `process_incoming_message_with_responses` raises any exception other than `SessionNotFound`, `TypeError`, or `ValueError`
- **THEN** the handler does not catch the exception; FastAPI's default handler turns it into HTTP 500 with the original exception preserved

### Requirement: Validation exception translation

The route handler SHALL translate the inner pipeline's validation exceptions into HTTP 400 responses. Specifically: when `process_incoming_message_with_responses` raises `TypeError` (because `message` is not a `str`) or `ValueError` (because `message` is empty after `strip()`), the handler SHALL raise `HTTPException(status_code=400, detail=str(exc))` chained from the original exception, and the route SHALL return HTTP 400 with that detail string in the JSON body.

#### Scenario: TypeError becomes HTTP 400

- **WHEN** `process_incoming_message_with_responses(db, session, message)` raises `TypeError("message must be a str")`
- **THEN** the handler raises `HTTPException(status_code=400, detail="message must be a str")` and the route returns HTTP 400

#### Scenario: ValueError becomes HTTP 400

- **WHEN** `process_incoming_message_with_responses(db, session, message)` raises `ValueError("message must be a non-empty, non-whitespace string")`
- **THEN** the handler raises `HTTPException(status_code=400, detail="message must be a non-empty, non-whitespace string")` and the route returns HTTP 400

#### Scenario: Empty message produces HTTP 400 from the inner pipeline

- **WHEN** the request body is `{"message": ""}` and `SessionService.get_active` returns a session
- **THEN** `process_incoming_message_with_responses` is invoked with `""`; the inner pipeline raises `ValueError`; the handler translates it to `HTTPException(400)` and the route returns HTTP 400

#### Scenario: Whitespace-only message produces HTTP 400 from the inner pipeline

- **WHEN** the request body is `{"message": "   \n\t  "}` and `SessionService.get_active` returns a session
- **THEN** `process_incoming_message_with_responses` is invoked with the whitespace string; the inner pipeline raises `ValueError`; the handler translates it to `HTTPException(400)` and the route returns HTTP 400

### Requirement: Response payload shape

The route SHALL return an `IncomingMessageResponse` whose `responses` field is the `list[CustomerResponse]` produced by `process_incoming_message_with_responses`, in the same order, with the same length. The route SHALL NOT wrap the list in additional metadata fields, transform the customer responses, or add a top-level `session_id` / `comercio_id` / `timestamp`.

#### Scenario: agregar_producto response is returned as the responses field

- **WHEN** the inner call returns `[CustomerResponse(message="Listo, agregué 2 Pizza Mozzarella grande.", intent="agregar_producto", status="executed")]`
- **THEN** the route returns HTTP 200 with `{"responses": [{"message": "Listo, agregué 2 Pizza Mozzarella grande.", "intent": "agregar_producto", "status": "executed"}]}`

#### Scenario: Unsupported intent response uses the generic message

- **WHEN** the inner call returns `[CustomerResponse(message=GENERIC_MESSAGE, intent="desconocida", status="rejected")]`
- **THEN** the route returns HTTP 200 with `{"responses": [{"message": <GENERIC_MESSAGE>, "intent": "desconocida", "status": "rejected"}]}`

#### Scenario: Multiple intents preserve the inner order

- **WHEN** the inner call returns three customer responses in the order `[agregar_producto executed, agregar_producto pending_resolution, desconocida rejected]`
- **THEN** the route returns HTTP 200 with `{"responses": [...]}` whose three elements are in the same order

### Requirement: No LLM, transaction, repository, or mutation imports in the router

The router module SHALL NOT import `requests`, `fastapi` decorators other than the documented `APIRouter` / `HTTPException` / `Depends` / `status`, `twilio`, `asyncio`, `backend.old_project`, `backend.llm.*`, `backend.repositories.*`, `backend.intents.handlers.*`, `backend.intents.context.*`, `backend.intents.recognizers.*`, `backend.intents.resolvers.*`, `backend.intents.processor`, `backend.intents.contracts.*`, `backend.intents.orchestration.*` other than the documented `process_incoming_message_with_responses` import, or any queue / Twilio / messaging-response module. The router SHALL NOT call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`. Transaction ownership remains with `process_incoming_message_with_responses` (through the transactional processor).

#### Scenario: Router does not import old_project, LLM, repositories, or transports

- **WHEN** `backend/routers/incoming_messages.py` is inspected
- **THEN** its imports do not include `backend.old_project`, `backend.llm`, `backend.repositories`, `backend.intents.handlers`, `backend.intents.context`, `backend.intents.recognizers`, `backend.intents.resolvers`, `backend.intents.processor`, `backend.intents.contracts`, `backend.intents.orchestration` other than `process_incoming_message_with_responses`, `requests`, `twilio`, `asyncio`, or `MessagingResponse`

#### Scenario: Router does not call any transaction method

- **WHEN** the route handler runs against a `MagicMock(name="DatabaseSession")` whose `commit`, `rollback`, `flush`, `refresh`, `expire`, and `begin` are mocks
- **THEN** `db.commit.assert_not_called()`, `db.rollback.assert_not_called()`, `db.flush.assert_not_called()`, `db.refresh.assert_not_called()`, `db.expire.assert_not_called()`, and `db.begin.assert_not_called()` after both the success path and any translated-exception path

#### Scenario: Router does not log, retry, or go async

- **WHEN** the router module source is inspected
- **THEN** it does not contain `logging.`, `logger.`, `print(`, `time.sleep`, `asyncio`, `await`, `async def`, `retry`, or `backoff`

### Requirement: Public surface is limited

The router module SHALL export only `router` through `__all__` and SHALL NOT introduce additional helpers, route decorators, sub-routers, dependency factories other than the documented `_service` factory, or background tasks.

#### Scenario: Only router is exported

- **WHEN** `backend.routers.incoming_messages` is imported and `__all__` is inspected
- **THEN** `__all__` equals ["router"]

#### Scenario: Module has exactly one route decorator

- **WHEN** the router module source is inspected for `@router.` decorators
- **THEN** exactly one `@router.post(...)` decorator is present and no `@router.get`, `@router.put`, `@router.patch`, or `@router.delete` decorator is present
