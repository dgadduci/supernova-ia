# Capability: quitar-producto-customer-response

## Purpose

Provide a deterministic response builder for `quitar_producto` that converts every `ProcessedIntent` outcome (`pending_resolution`, `executed` partial, `executed` complete, `rejected` excess quantity, `rejected` absent, `failed`) into a single fixed Spanish `CustomerResponse` without LLM beautification, internal IDs, or technical detail, and without leaking the underlying catalog.

## Requirements

### Requirement: Customer response module location

The system SHALL expose `build_quitar_producto_response` from `backend/intents/responses/quitar_producto_response.py`.

#### Scenario: Response builder is importable
- **WHEN** a module executes `from backend.intents.responses.quitar_producto_response import build_quitar_producto_response`
- **THEN** the import succeeds and the binding is callable

### Requirement: Response builder signature

The system SHALL expose `build_quitar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model.

#### Scenario: Function is callable with the documented signature
- **WHEN** a caller invokes `build_quitar_producto_response(db, session, intent)`
- **THEN** the function returns a `CustomerResponse` without raising

### Requirement: pending_resolution message lists only refined candidates

When `intent.status == "pending_resolution"`, the response SHALL be exactly `¿Cuál querés quitar: <candidate1> o <candidate2>( o <candidateN>)?`, where each `<candidateN>` is the formatted `producto_nombre (presentacion_codigo)` of the corresponding `pedido_producto_id` resolved through `PedidoProductoService.list_by_pedido`. The response SHALL NOT contain any database ID, SHALL NOT include products absent from the pedido, and SHALL NOT include products absent from `intent.candidate_ids`.

#### Scenario: Two candidates render as ¿Cuál querés quitar: A o B?
- **WHEN** the active intent has `candidate_ids` with two `pedido_producto_id` values for `Pizza de Muzzarella Grande` and `Pizza Napolitana Grande`
- **THEN** the response message is exactly `¿Cuál querés quitar: Pizza de Muzzarella Grande (grande) o Pizza Napolitana Grande (grande)?`

#### Scenario: Three candidates use repeated "o" join
- **WHEN** the active intent has `candidate_ids` with three values
- **THEN** the response joins the formatted candidates with ` o ` and the final join is ` o ` (no trailing connector)

#### Scenario: Candidate not in pedido is not listed
- **WHEN** `intent.candidate_ids` contains an id that does not resolve through `PedidoProductoService.list_by_pedido`
- **THEN** the builder skips that id and joins only the resolvable ones; if none resolve, the message falls back to a generic clarification

### Requirement: executed message for partial removal

When `intent.status == "executed"` and `resolved_data["linea_eliminada"] is False`, the response SHALL be exactly `Quité {cantidad_removida} {producto_nombre} ({presentacion_codigo}). Queda {cantidad_restante} en tu pedido.`. The numbers SHALL come from `resolved_data`, not from a fresh DB lookup.

#### Scenario: Decrement returns a Quité X ... Queda Y message
- **WHEN** the executed intent has `cantidad_removida=2`, `cantidad_restante=1`, `producto_nombre="Empanadas de carne"`, `presentacion_codigo="docena"`
- **THEN** the response message is exactly `Quité 2 Empanadas de carne (docena). Queda 1 en tu pedido.`

### Requirement: executed message for complete removal

When `intent.status == "executed"` and `resolved_data["linea_eliminada"] is True`, the response SHALL be exactly `Quité {producto_nombre} ({presentacion_codigo}) de tu pedido.`.

#### Scenario: Line deletion returns a Quité X de tu pedido message
- **WHEN** the executed intent has `producto_nombre="Pizza de Muzzarella"`, `presentacion_codigo="grande"`, `linea_eliminada=True`
- **THEN** the response message is exactly `Quité Pizza de Muzzarella (grande) de tu pedido.`

### Requirement: rejected message for excess quantity

When `intent.status == "rejected"` and `resolved_data` carries `cantidad_actual` and the product / presentation identifiers, the response SHALL be exactly `Solo tenés {cantidad_actual} {producto_nombre} ({presentacion_codigo}) en el pedido.`.

#### Scenario: Excess quantity returns a Solo tenés ... message
- **WHEN** the rejected intent has `cantidad_actual=2`, `producto_nombre="Empanadas de carne"`, `presentacion_codigo="docena"`
- **THEN** the response message is exactly `Solo tenés 2 Empanadas de carne (docena) en el pedido.`

### Requirement: rejected message for absent product

When `intent.status == "rejected"` and the reason is that the product is not in the draft pedido (no `cantidad_actual` in `resolved_data` and no candidate resolved), the response SHALL be exactly `Ese producto no está en tu pedido.`.

#### Scenario: Absent product returns a fixed Spanish message
- **WHEN** the rejected intent has no `cantidad_actual` and no `pedido_producto_id`
- **THEN** the response message is exactly `Ese producto no está en tu pedido.`

### Requirement: failed message is generic

When `intent.status == "failed"`, the response SHALL be a single fixed Spanish string with no technical detail, no stack trace, no id, and no per-call formatting. The literal string SHALL be `No pude procesar tu pedido. Intentá de nuevo en un momento.`.

#### Scenario: Failed intent returns the generic retry message
- **WHEN** the intent has `status == "failed"`
- **THEN** the response message equals the documented generic string and contains no literal `id`, `Exception`, `Traceback`, `Error`, or `pedido_producto`

### Requirement: Response orchestration metadata

Every `CustomerResponse` produced by the builder SHALL carry `intent == "quitar_producto"` and `status` equal to the source `intent.status`.

#### Scenario: Intent and status fields are preserved
- **WHEN** the builder runs for any of the documented outcomes
- **THEN** the returned `CustomerResponse.intent == "quitar_producto"` and `CustomerResponse.status == intent.status`

### Requirement: No LLM beautification

The response builder SHALL NOT call any LLM client, prompt construction helper, or third-party text-generation library. The message SHALL be assembled by string formatting in Python only.

#### Scenario: Builder has no LLM imports
- **WHEN** the builder module is imported
- **THEN** it does NOT import `backend.llm`, `QueryLlm`, or any client whose primary purpose is text generation

### Requirement: Public surface is limited

The response module SHALL export only `build_quitar_producto_response` through `__all__` and SHALL NOT introduce a registry or generic response-builder abstraction.

#### Scenario: Single public response symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["build_quitar_producto_response"]`
