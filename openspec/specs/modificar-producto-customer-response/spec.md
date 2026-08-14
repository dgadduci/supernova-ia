# Capability: modificar-producto-customer-response

## Purpose

Provide a deterministic response builder for `modificar_producto` that renders every outcome (source pending, destination pending, full-line executed, partial executed, consolidated executed, excess quantity, source absent, destination unavailable, source equals destination, generic failed) using only the order lines, presentations, and product names already loaded by the orchestration layer, without LLM beautification, prompt construction, or exposure of database identifiers.
## Requirements
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

When `intent.status == "executed"` and `resolved_data["origen_eliminado"] is True` and `resolved_data["destino_creado"] is True`, the builder SHALL render `Cambié <cantidad_a_modificar> <origen_nombre> por <cantidad_a_modificar> <destino_nombre>.`

#### Scenario: Full-line swap with omitted quantity renders the corrected message

- **WHEN** the service reports a full-line swap with `cantidad_modificada == 4`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`, `presentacion_origen` and `presentacion_destino` omitted from the rendered message because the full transfer quantity equals the source quantity
- **THEN** `CustomerResponse.message` equals `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.`

### Requirement: Partial modification executed rendering

When `intent.status == "executed"` and `resolved_data["destino_creado"] is True` and `resolved_data["origen_eliminado"] is False` (a partial modification where the source is decremented and a new destination line is created), the builder SHALL render `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`

#### Scenario: Partial empanada modification renders the documented message

- **WHEN** `cantidad_modificada == 2`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`, `cantidad_origen_restante == 3`
- **THEN** `CustomerResponse.message` equals `Cambié 2 Empanadas de Verdura por 2 de Empanadas de Carne Picante. Quedan 3 Empanadas de Verdura.`

### Requirement: Consolidated destination executed rendering

When `intent.status == "executed"` and `resolved_data["destino_creado"] is False` (the destination line was incremented in place), the builder SHALL render `Cambié <cantidad_origen> <origen_nombre> (<origen_presentacion>) por <destino_nombre> (<destino_presentacion>). Ahora tenés <cantidad_destino_final> <destino_nombre> (<destino_presentacion>).`

#### Scenario: Consolidated modification renders the documented message

- **WHEN** `cantidad_origen == 2`, `origen_nombre="pizzas"`, `origen_presentacion="chicas"`, `destino_nombre="pizzas"`, `destino_presentacion="grandes"`, `cantidad_destino_final == 4`
- **THEN** `CustomerResponse.message` equals `Cambié 2 pizzas chicas por grandes. Ahora tenés 4 pizzas grandes.`

### Requirement: Excess quantity rejected rendering

When `intent.status == "rejected"` and the rejection reason is `quantity_exceeds_source`, the builder SHALL render `Solo tenés <cantidad_actual> <origen_nombre> para cambiar. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Excess quantity renders the Pedido-preserved message

- **WHEN** `cantidad_actual == 3`, `origen_nombre="Empanadas de Verdura"`
- **THEN** `CustomerResponse.message` equals `Solo tenés 3 Empanadas de Verdura para cambiar. Tu pedido no fue modificado.`

### Requirement: Source absent rejected rendering

When `intent.status == "rejected"` and the rejection reason is `source_not_in_pedido`, the builder SHALL render `Ese producto no está en tu pedido.`

#### Scenario: Source absent renders the documented message

- **WHEN** the rejection reason is `source_not_in_pedido`
- **THEN** `CustomerResponse.message` equals `Ese producto no está en tu pedido.`

### Requirement: Destination unavailable rejected rendering

When `intent.status == "rejected"` and the rejection reason is `destination_unavailable` (including the unknown-destination case surfaced as `destination_unavailable`), the builder SHALL render `El producto de reemplazo no está disponible. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Destination unavailable renders the Pedido-preserved message

- **WHEN** the rejection reason is `destination_unavailable`
- **THEN** `CustomerResponse.message` equals `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`

### Requirement: Unknown destination rejected rendering

When `intent.status == "rejected"` and the destination product does not exist in the comercio catalog (the unknown-destination case surfaced as `destination_unavailable` or `no_destination_candidates`), the builder SHALL render `No encontré el producto de reemplazo. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Unknown destination renders the documented message

- **WHEN** the rejection reason is `destination_unavailable` and the destination product does not exist in the comercio catalog
- **THEN** `CustomerResponse.message` equals `No encontré el producto de reemplazo. Tu pedido no fue modificado.`

### Requirement: Single customer response per modification

The response builder SHALL be invoked exactly once per `modificar_producto` outcome. The system SHALL NOT produce a remove response followed by an add response, SHALL NOT produce two `CustomerResponse` instances per modification, and SHALL NOT split the modification across multiple response builders. The incoming-message response orchestrator SHALL route every `modificar_producto` outcome to `build_modificar_producto_response` and SHALL NOT use the generic fallback.

#### Scenario: Exactly one CustomerResponse per modification

- **WHEN** `process_incoming_message_transactional(db, session, message)` returns for a `modificar_producto` message
- **THEN** `build_modificar_producto_response` is invoked exactly once and the response orchestrator emits exactly one `CustomerResponse`

#### Scenario: No separate remove and add responses

- **WHEN** the user sends `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the rendered `CustomerResponse.message` is the single modification message; the response does not contain `Quité` and `Agregué` substrings together

#### Scenario: Response orchestrator never uses the generic fallback for modificar_producto

- **WHEN** the active intent is `modificar_producto` for any status
- **THEN** `incoming_message_response_orchestrator` delegates to `build_modificar_producto_response` and never to the generic fallback builder

### Requirement: Executed partial explicit-quantity message format

When `intent.status == "executed"` and `resolved_data["destino_creado"] is True` and `resolved_data["origen_eliminado"] is False` (a partial modification where the source is decremented and a new destination line is created), the builder SHALL render `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`

#### Scenario: Partial explicit-quantity transfer renders the corrected message

- **WHEN** `cantidad_modificada == 2`, `cantidad_origen_restante == 3`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`
- **THEN** `CustomerResponse.message` equals `Cambié 2 Empanadas de Verdura por 2 de Empanadas de Carne Picante. Quedan 3 Empanadas de Verdura.`

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

### Requirement: Real-flow response matrix

When driven by the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or by the interactive CLI driver, the response builder SHALL render the deterministic message matrix for both reproduction phrases.

#### Scenario: HTTP response for defect 1 renders the corrected full-transfer message

- **WHEN** the real HTTP endpoint receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** `CustomerResponse.message` equals `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.` (or its equivalent product-name substitution for the seeded catalog); the message contains the explicit quantity `4` on both sides and never the literal `1`

#### Scenario: CLI response for defect 1 prints the corrected full-transfer message

- **WHEN** the interactive CLI driver at `backend/scripts/cli_chat_client.py` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the CLI prints the single modification message `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.` (or its equivalent product-name substitution for the seeded catalog); the printed output never contains `Quité` and `Agregué` substrings together for the same modification

#### Scenario: HTTP response for defect 2 renders the unknown-destination message

- **WHEN** the real HTTP endpoint receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** `CustomerResponse.message` equals `No encontré el producto de reemplazo. Tu pedido no fue modificado.`; the message confirms the Pedido is unchanged

#### Scenario: CLI response for defect 2 prints the unknown-destination message

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the CLI prints the unknown-destination message `No encontré el producto de reemplazo. Tu pedido no fue modificado.` and the printed order table shows the source line unchanged

### Requirement: Real-flow single response invariant

When driven by the real HTTP endpoint or the interactive CLI driver, the response builder SHALL be invoked exactly once per `modificar_producto` outcome; the system SHALL NOT produce two `CustomerResponse` instances for a single modification message.

#### Scenario: HTTP emits one CustomerResponse per modification

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the response orchestrator emits exactly one `CustomerResponse`; the response list never contains two `CustomerResponse` entries for the same modification

#### Scenario: CLI prints one modification response per message

- **WHEN** the interactive CLI driver processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the CLI prints exactly one modification response block; the printed output never contains two modification responses for the same modification

### Requirement: Real-flow Pedido-preserved confirmation

When driven by the real HTTP endpoint or the interactive CLI driver, every rejected `modificar_producto` outcome SHALL render a message that explicitly confirms the Pedido is unchanged (`Tu pedido no fue modificado.`). The confirmation MUST appear for: unknown destination; unavailable destination; foreign-comercio destination; equivalent modification; excess quantity; source absent.

#### Scenario: HTTP confirms Pedido unchanged on rejected outcomes

- **WHEN** the real HTTP endpoint processes a `modificar_producto` message whose service result is `rejected` for any deterministic reason
- **THEN** the rendered `CustomerResponse.message` contains the `Tu pedido no fue modificado.` confirmation substring (or, for `source_not_in_pedido` and `equivalent_modification`, the equivalent documented rejection message)

#### Scenario: CLI confirms Pedido unchanged on rejected outcomes

- **WHEN** the interactive CLI driver processes a `modificar_producto` message whose service result is `rejected` for any deterministic reason
- **THEN** the printed customer response confirms the Pedido is unchanged (or, for `source_not_in_pedido` and `equivalent_modification`, prints the equivalent documented rejection message); the printed order table after the rejection reflects the unchanged Pedido state

### Requirement: Distinct quantity confirmation reflects durable mutation

For an executed modification with distinct source and destination operation
amounts, the customer response SHALL render both actual values and must not
reuse the source value for destination. Existing wording for equal-quantity
legacy outcomes remains unchanged.

#### Scenario: Confirmation of 2 to 1 partial replacement

- **WHEN** the durable operation decrements Napolitana by 2, increments Mozzarella by 1, and leaves 5 Napolitana
- **THEN** the confirmation communicates 2 Napolitana replaced by 1 Mozzarella and that 5 Napolitana remain

#### Scenario: Consolidated destination reports the actual destination total

- **WHEN** the destination already existed and the distinct operation adds 1 unit
- **THEN** the response may include the durable destination final total, but never reports the source amount as the amount added to destination
