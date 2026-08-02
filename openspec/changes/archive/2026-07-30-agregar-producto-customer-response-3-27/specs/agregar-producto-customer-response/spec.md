## ADDED Requirements

### Requirement: Customer response schema

The system SHALL expose `CustomerResponse` from `backend/intents/schemas/customer_response.py` as a Pydantic `BaseModel` with exactly three string fields: `message: str`, `intent: str`, `status: str`. The module SHALL export only `CustomerResponse` through `__all__`.

#### Scenario: CustomerResponse is importable

- **WHEN** a module executes `from backend.intents.schemas.customer_response import CustomerResponse`
- **THEN** the import succeeds and the binding is a Pydantic `BaseModel` subclass

#### Scenario: CustomerResponse has exactly three string fields

- **WHEN** a caller constructs `CustomerResponse(message="hola", intent="agregar_producto", status="executed")`
- **THEN** the resulting model exposes `message`, `intent`, and `status` as strings equal to the values supplied

#### Scenario: Module exports only CustomerResponse

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["CustomerResponse"]`

### Requirement: Customer response builder module location

The system SHALL expose `build_agregar_producto_response` from `backend/intents/responses/agregar_producto_response.py`. The module SHALL live inside a new `backend/intents/responses/` package (with an empty `__init__.py`).

#### Scenario: Response builder is importable

- **WHEN** a module executes `from backend.intents.responses.agregar_producto_response import build_agregar_producto_response`
- **THEN** the import succeeds and the binding is callable

### Requirement: Customer response builder signature

The builder SHALL expose the single function `build_agregar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse`, using the typed aliases `Session as DatabaseSession` (from `sqlalchemy.orm`) and `Session as ConversationSession` (from `backend.models.session`). The module SHALL export only `build_agregar_producto_response` through `__all__`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `build_agregar_producto_response(db, session, intent)`
- **THEN** the function returns a `CustomerResponse` instance without raising for any of the four documented intent statuses (`pending_resolution`, `executed`, `rejected`, `failed`)

#### Scenario: Module exports only the response builder

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["build_agregar_producto_response"]`

### Requirement: Intent scope is limited to agregar_producto

The builder SHALL accept any `ProcessedIntent` instance but SHALL return a generic apology `CustomerResponse` for any `intent.intent != "agregar_producto"`. The returned `CustomerResponse.intent` SHALL equal `intent.intent` and the returned `CustomerResponse.status` SHALL equal `intent.status` regardless of which branch produced the message.

#### Scenario: Non-agregar_producto intent returns the apology fallback

- **WHEN** the builder receives a `ProcessedIntent` whose `intent == "consultar_pedido"` and any `status`
- **THEN** the returned `CustomerResponse.message` is the fixed apology message, `CustomerResponse.intent == "consultar_pedido"`, and `CustomerResponse.status` equals `intent.status`

### Requirement: Pending resolution clarification

For `intent.intent == "agregar_producto"` and `intent.status == "pending_resolution"` with non-empty `candidate_ids`, the builder SHALL load the candidate product-presentations through `ProductoQueryService.list_presentaciones_by_ids(intent.candidate_ids)` and SHALL return a `CustomerResponse` whose `message` lists each available product + presentation pair in the order returned by the service, joined by commas with the conjunction `"o"` before the last entry. The message SHALL NOT include database IDs, prices, stock flags, quantities, or the literal string `"id"`.

#### Scenario: Two candidates yield a two-option clarification

- **WHEN** the builder receives a `pending_resolution` intent whose `candidate_ids == [pp_id_chica, pp_id_grande]` and both presentations resolve through the service to `("Pizza Mozzarella", "chica")` and `("Pizza Mozzarella", "grande")`
- **THEN** the returned `CustomerResponse.message` contains both `"Pizza Mozzarella"` and both presentation names (`"chica"`, `"grande"`), joined with an `"o"` before the last entry, and does NOT contain the literal `str(pp_id_chica)`, `str(pp_id_grande)`, or the literal string `"id"`

#### Scenario: Empty candidate_ids falls back to the apology message

- **WHEN** the builder receives a `pending_resolution` intent whose `candidate_ids == []`
- **THEN** the returned `CustomerResponse.message` equals the fixed apology message and `CustomerResponse.status == "pending_resolution"`

### Requirement: Executed confirmation

For `intent.intent == "agregar_producto"` and `intent.status == "executed"`, the builder SHALL read `resolved_data["producto_presentacion_id"]` and `resolved_data["cantidad"]`, load the presentation through `ProductoQueryService.list_presentaciones_by_ids([producto_presentacion_id])`, and return a `CustomerResponse` whose `message` confirms the product name, presentation name, and quantity added. The quantity phrasing SHALL use the singular form when `cantidad == 1` and the plural form when `cantidad > 1`. The message SHALL NOT include database IDs or prices.

#### Scenario: Executed intent with cantidad == 1 confirms one unit

- **WHEN** the builder receives an `executed` intent whose `resolved_data == {"producto_presentacion_id": pp_id, "cantidad": 1}` and the service returns `("Pizza Mozzarella", "grande")`
- **THEN** the returned `CustomerResponse.message` contains `"Pizza Mozzarella"`, `"grande"`, the literal `"1"`, and the singular phrasing marker (e.g., `"agregué"`), and does NOT contain `str(pp_id)` or any price string

#### Scenario: Executed intent with cantidad == 2 confirms multiple units

- **WHEN** the builder receives an `executed` intent whose `resolved_data == {"producto_presentacion_id": pp_id, "cantidad": 2}` and the service returns `("Pizza Mozzarella", "grande")`
- **THEN** the returned `CustomerResponse.message` contains `"Pizza Mozzarella"`, `"grande"`, the literal `"2"`, and does NOT contain `str(pp_id)` or any price string

#### Scenario: Executed intent with missing presentation returns the failed fallback

- **WHEN** the builder receives an `executed` intent whose `resolved_data["producto_presentacion_id"]` does not resolve through the service
- **THEN** the returned `CustomerResponse.message` equals the fixed retry message, `CustomerResponse.intent == "agregar_producto"`, and `CustomerResponse.status == "failed"`

#### Scenario: Executed intent with invalid cantidad returns the failed fallback

- **WHEN** the builder receives an `executed` intent whose `resolved_data["cantidad"]` is missing, non-integer, or less than 1
- **THEN** the returned `CustomerResponse.message` equals the fixed retry message and `CustomerResponse.status == "failed"`

### Requirement: Rejected apology

For `intent.intent == "agregar_producto"` and `intent.status == "rejected"`, the builder SHALL return a `CustomerResponse` whose `message` is the fixed apology string. The message SHALL NOT include IDs, exception messages, internal reasons, or technical detail.

#### Scenario: Rejected intent returns the apology message

- **WHEN** the builder receives a `rejected` intent
- **THEN** the returned `CustomerResponse.message` equals the fixed apology string, `CustomerResponse.intent == "agregar_producto"`, and `CustomerResponse.status == "rejected"`

### Requirement: Failed retry message

For `intent.intent == "agregar_producto"` and `intent.status == "failed"`, the builder SHALL return a `CustomerResponse` whose `message` is the fixed retry string. The message SHALL NOT include exception types, stack traces, IDs, or technical detail.

#### Scenario: Failed intent returns the retry message

- **WHEN** the builder receives a `failed` intent
- **THEN** the returned `CustomerResponse.message` equals the fixed retry string, `CustomerResponse.intent == "agregar_producto"`, and `CustomerResponse.status == "failed"`

### Requirement: No mutation, commit, rollback, or query inside the builder

The builder SHALL NOT mutate `session`, `intent`, or any model attribute; SHALL NOT call `db.commit`, `db.rollback`, `db.flush`, `db.refresh`, `db.expire`, or `db.begin`; SHALL NOT execute SQLAlchemy `select` / `execute` / `add` / `delete`; and SHALL NOT import any repository, `sqlalchemy.select`, `sqlalchemy.orm.joinedload`, `backend.old_project`, or any handler / dispatcher / queue module. All database access SHALL go through `ProductoQueryService.list_presentaciones_by_ids`.

#### Scenario: Builder does not commit, rollback, flush, refresh, or expire

- **WHEN** the builder is invoked against any of the four documented branches
- **THEN** the SQLAlchemy session passed as `db` does not have `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin` invoked by the builder

#### Scenario: Builder does not mutate session or intent

- **WHEN** the builder is invoked
- **THEN** `session.pending_intents`, `session.context_type`, `session.id_pedido`, and every field of `intent` equal the values they had before the call

#### Scenario: Builder performs no SQLAlchemy query directly

- **WHEN** the response module source is inspected
- **THEN** it does not import `sqlalchemy`, `sqlalchemy.orm.joinedload`, `backend.repositories.*`, or `backend.intents.orchestration.*`

### Requirement: No LLM, HTTP, Twilio, queue, or handler imports

The response module SHALL NOT import `requests`, `fastapi`, `twilio`, `backend.llm`, `backend.routers`, `backend.dependencies`, `backend.handlers`, `backend.intents.orchestration`, `backend.intents.context`, `backend.intents.handlers`, `backend.intents.resolvers`, `backend.intents.services`, or `backend.old_project`, and SHALL NOT instantiate an LLM client, build a Twilio message, format an HTTP response, or implement retry/backoff/async wrappers.

#### Scenario: Module is free of LLM, HTTP, Twilio, and handler imports

- **WHEN** `backend.intents.responses.agregar_producto_response` is imported
- **THEN** it does not import `requests`, `fastapi`, `twilio`, `backend.llm`, `backend.routers`, `backend.dependencies`, `backend.handlers`, `backend.intents.orchestration`, `backend.intents.context`, `backend.intents.handlers`, `backend.intents.resolvers`, `backend.intents.services`, or `backend.old_project`

#### Scenario: Module does not format HTTP responses or Twilio messages

- **WHEN** the response module source is inspected
- **THEN** it contains no `HTTPException`, no `Response(`, no `JSONResponse(`, no `MessagingResponse`, no `Client(`, and no LLM call

### Requirement: Public surface is limited

The response module SHALL export only `build_agregar_producto_response` through `__all__` and SHALL NOT introduce additional helpers, formatters, registries, multi-intent dispatchers, or response objects for other intents.

#### Scenario: Only one public symbol is exported

- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["build_agregar_producto_response"]`

#### Scenario: Module has no additional public functions

- **WHEN** the response module is inspected for top-level `def` statements other than `build_agregar_producto_response`
- **THEN** only `build_agregar_producto_response` is defined (private constants and imports are permitted)