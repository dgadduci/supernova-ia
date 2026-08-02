## ADDED Requirements

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