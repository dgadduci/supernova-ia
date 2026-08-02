# Capability: modificar-producto-customer-response

## Purpose

Provide a deterministic response builder for `modificar_producto` that renders every outcome (source pending, destination pending, full-line executed, partial executed, consolidated executed, excess quantity, source absent, destination unavailable, source equals destination, generic failed) using only the order lines, presentations, and product names already loaded by the orchestration layer, without LLM beautification, prompt construction, or exposure of database identifiers.

## ADDED Requirements

### Requirement: Response builder module location

The system SHALL expose `build_modificar_producto_response` from `backend/intents/responses/modificar_producto_response.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Response builder is importable from the modern intents responses package

- **WHEN** a module executes `from backend.intents.responses.modificar_producto_response import build_modificar_producto_response`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Response builder signature

The system SHALL expose `build_modificar_producto_response(db: DatabaseSession, session: ConversationSession, intent: ProcessedIntent) -> CustomerResponse` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `build_modificar_producto_response(db, session, intent)` for any `modificar_producto` outcome
- **THEN** the builder returns a `CustomerResponse` without raising

### Requirement: Response intent and status preservation

The builder SHALL set `CustomerResponse.intent == "modificar_producto"` and `CustomerResponse.status == intent.status` for every outcome.

#### Scenario: Intent and status are preserved

- **WHEN** `build_modificar_producto_response(db, session, intent)` returns for any branch
- **THEN** the resulting `CustomerResponse.intent == "modificar_producto"` and `CustomerResponse.status == intent.status`

### Requirement: Source pending resolution rendering

When `intent.status == "pending_resolution"` and `intent.stage == "source_selection"`, the builder SHALL render `¿Cuál producto querés cambiar: <a> o <b>( o <c>)?` from formatted `producto_nombre (presentacion_codigo)` pairs resolved through `PedidoProductoService.list_by_pedido` for each source candidate.

#### Scenario: Two source candidates render with "o"

- **WHEN** `source_candidate_ids == [<id_a>, <id_b>]` resolves to `Pizza de Muzzarella Chica` and `Pizza Napolitana Grande`
- **THEN** `CustomerResponse.message` equals `¿Cuál producto querés cambiar: Pizza de Muzzarella Chica o Pizza Napolitana Grande?`

#### Scenario: Three source candidates render with commas and final "o"

- **WHEN** `source_candidate_ids == [<id_a>, <id_b>, <id_c>]` resolves to three formatted products
- **THEN** `CustomerResponse.message` joins the first two with `, ` and the last with ` o `

### Requirement: Destination pending resolution rendering

When `intent.status == "pending_resolution"` and `intent.stage == "destination_selection"`, the builder SHALL render `¿Cuál querés como reemplazo: <a>, <b> o <c>?` from formatted `producto_nombre (presentacion_codigo)` pairs resolved through the existing product-query service for each destination candidate.

#### Scenario: Multiple destination candidates render correctly

- **WHEN** `destination_candidate_ids == [<id_x>, <id_y>, <id_z>]` resolves to `Pizza de Muzzarella Grande`, `Pizza Napolitana Grande`, and `Pizza Margherita Grande`
- **THEN** `CustomerResponse.message` equals `¿Cuál querés como reemplazo: Pizza de Muzzarella Grande, Pizza Napolitana Grande o Pizza Margherita Grande?`

### Requirement: Full-line executed rendering

When `intent.status == "executed"` and `resolved_data["origen_eliminado"] is True` and `resolved_data["destino_creado"] is True`, the builder SHALL render `Cambié <origen_nombre> (<origen_presentacion>) por <destino_nombre> (<destino_presentacion>).`

#### Scenario: Full-line swap renders the documented message

- **WHEN** the service reports a full-line swap with `producto_origen_nombre="Pizza de Muzzarella"`, `presentacion_origen="Chica"`, `producto_destino_nombre="Pizza de Muzzarella"`, `presentacion_destino="Grande"`
- **THEN** `CustomerResponse.message` equals `Cambié Pizza de Muzzarella (Chica) por Pizza de Muzzarella (Grande).`

### Requirement: Partial modification executed rendering

When `intent.status == "executed"` and `resolved_data["cantidad_modificada"] < resolved_data["cantidad_origen_restante"] + resolved_data["cantidad_modificada"]`, the builder SHALL render `Cambié <cantidad_modificada> <origen_nombre> (<origen_presentacion>) por <cantidad_modificada> de <destino_nombre> (<destino_presentacion>). Quedan <cantidad_origen_restante> <origen_nombre> (<origen_presentacion>).`

#### Scenario: Partial empanada modification renders the documented message

- **WHEN** `cantidad_modificada == 2`, `producto_origen_nombre="empanadas de carne"`, `producto_destino_nombre="empanadas de jamón y queso"`, `cantidad_origen_restante == 3`
- **THEN** `CustomerResponse.message` equals `Cambié 2 empanadas de carne por 2 de jamón y queso. Quedan 3 empanadas de carne.`

### Requirement: Consolidated destination executed rendering

When `intent.status == "executed"` and `resolved_data["destino_creado"] is False` (the destination line was incremented in place), the builder SHALL render `Cambié <cantidad_origen> <origen_nombre> (<origen_presentacion>) por <destino_nombre> (<destino_presentacion>). Ahora tenés <cantidad_destino_final> <destino_nombre> (<destino_presentacion>).`

#### Scenario: Consolidated modification renders the documented message

- **WHEN** `cantidad_origen == 2`, `origen_nombre="pizzas"`, `origen_presentacion="chicas"`, `destino_nombre="pizzas"`, `destino_presentacion="grandes"`, `cantidad_destino_final == 4`
- **THEN** `CustomerResponse.message` equals `Cambié 2 pizzas chicas por grandes. Ahora tenés 4 pizzas grandes.`

### Requirement: Excess quantity rejected rendering

When `intent.status == "rejected"` and the rejection reason is `quantity_exceeds_source`, the builder SHALL render `Solo tenés <cantidad_actual> <origen_nombre> (<origen_presentacion>) para cambiar.`

#### Scenario: Excess quantity renders the documented message

- **WHEN** `cantidad_actual == 2`, `origen_nombre="empanadas de carne"`, `origen_presentacion="unidad"`
- **THEN** `CustomerResponse.message` equals `Solo tenés 2 empanadas de carne para cambiar.`

### Requirement: Source absent rejected rendering

When `intent.status == "rejected"` and the rejection reason is `source_not_in_pedido`, the builder SHALL render `Ese producto no está en tu pedido.`

#### Scenario: Source absent renders the documented message

- **WHEN** the rejection reason is `source_not_in_pedido`
- **THEN** `CustomerResponse.message` equals `Ese producto no está en tu pedido.`

### Requirement: Destination unavailable rejected rendering

When `intent.status == "rejected"` and the rejection reason is `destination_unavailable`, the builder SHALL render `Ese producto no está disponible como reemplazo.`

#### Scenario: Destination unavailable renders the documented message

- **WHEN** the rejection reason is `destination_unavailable`
- **THEN** `CustomerResponse.message` equals `Ese producto no está disponible como reemplazo.`

### Requirement: Equivalent modification rejected rendering

When `intent.status == "rejected"` and the rejection reason is `equivalent_modification`, the builder SHALL render `Ese producto ya tiene esa presentación en tu pedido.`

#### Scenario: Equivalent modification renders the documented message

- **WHEN** the rejection reason is `equivalent_modification`
- **THEN** `CustomerResponse.message` equals `Ese producto ya tiene esa presentación en tu pedido.`

### Requirement: Failed rendering

When `intent.status == "failed"`, the builder SHALL render the generic retry message `No pude procesar tu pedido. Intentá de nuevo en un momento.` and SHALL NOT include technical details.

#### Scenario: Failed renders the generic retry message

- **WHEN** `intent.status == "failed"`
- **THEN** `CustomerResponse.message` equals the generic retry constant and does NOT contain the literal strings `"id"`, `"Exception"`, `"Traceback"`, or `"Error"`

### Requirement: No LLM, prompt construction, or DB ID exposure

The builder SHALL NOT invoke any LLM client, build any prompt, or expose any database identifier (`pedido_producto.id`, `producto_presentacion.id`, etc.) in the rendered message. Only product names, presentation codes, and quantities appear in the message body.

#### Scenario: Builder does not import LLM modules

- **WHEN** the builder module source is inspected
- **THEN** it does not import any LLM client, `backend.llm.*`, `backend.intents.llm.*`, or any prompt-construction module

#### Scenario: Message contains no database identifiers

- **WHEN** `build_modificar_producto_response` renders any outcome
- **THEN** `CustomerResponse.message` does not match the regular expression `\b\d{2,}\b` except for the human-readable quantity tokens explicitly required by the documented message templates

### Requirement: No commit, rollback, or HTTP side effects

The builder SHALL NOT issue `db.commit()`, `db.rollback()`, or generate HTTP responses. The builder only reads through existing services and constructs `CustomerResponse` instances.

#### Scenario: Builder performs no commit or rollback

- **WHEN** `build_modificar_producto_response(db, session, intent)` returns for any branch
- **THEN** `db.commit` and `db.rollback` have not been called by the builder module

#### Scenario: Builder does not import HTTP modules

- **WHEN** the builder module source is inspected
- **THEN** it does not import `requests`, `fastapi`, `twilio`, `backend.routers`, or any response-shaping helper beyond `CustomerResponse`

### Requirement: Public surface is limited

The response builder module SHALL export only `build_modificar_producto_response` through `__all__` and SHALL NOT introduce additional helpers, registries, or response objects.

#### Scenario: Only one public symbol is exported

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["build_modificar_producto_response"]`
