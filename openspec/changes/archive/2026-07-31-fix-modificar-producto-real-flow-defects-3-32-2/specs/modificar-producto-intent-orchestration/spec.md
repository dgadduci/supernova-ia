## ADDED Requirements

### Requirement: Real-flow initial orchestration invariants

When the user message arrives through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or through the interactive CLI driver, `process_initial_modificar_producto` SHALL preserve the 3.32.1 invariants: it SHALL NOT substitute `1` for an omitted quantity; it SHALL persist `cantidad is None` as the omitted-quantity sentinel across turns; it SHALL preserve the resolved source ID and the original quantity across destination-selection turns; it SHALL NOT mutate the source before the destination is ready; it SHALL emit exactly one `ProcessedIntent` per message.

#### Scenario: HTTP endpoint drives the omitted-quantity invariant

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** `process_initial_modificar_producto` returns a `ready` `ProcessedIntent` whose `resolved_data["cantidad"]` is `None` (not `1`); the orchestrator persists the omitted-quantity sentinel without substitution; the handler re-reads the source quantity and the destination row has `cantidad == 4`

#### Scenario: CLI driver drives the omitted-quantity invariant

- **WHEN** the interactive CLI driver at `backend/scripts/cli_chat_client.py` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the orchestrator returns a `ready` `ProcessedIntent` whose `resolved_data["cantidad"]` is `None`; the handler re-reads `cantidad == 4`; the destination row has `cantidad == 4`

#### Scenario: HTTP endpoint preserves source when destination is rejected

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the orchestrator returns a `rejected` `ProcessedIntent` with `reason="no_destination_candidates"`; the source row remains `cantidad == 5`; no destination row is created; `Session.context_type` is `None`

#### Scenario: CLI driver preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the orchestrator returns a `rejected` `ProcessedIntent`; the source row remains `cantidad == 5`; no destination row is created; the printed order table reflects the unchanged Pedido

### Requirement: Real-flow pending-context preservation

When the user message arrives through the real HTTP endpoint or the interactive CLI driver, the pending-context lifecycle MUST hold: an `executed` outcome clears the pending context; a definitive `rejected` outcome clears the pending context; an `failed` outcome preserves the pending context; a raised technical exception propagates for rollback.

#### Scenario: HTTP clears the pending context after definitive outcome

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message whose outcome is `executed` or `rejected`
- **THEN** the `Session.context_type` is `None` and the persisted `pending_intents` no longer carries the `modificar_producto` active intent

#### Scenario: CLI clears the pending context after definitive outcome

- **WHEN** the interactive CLI driver processes any `modificar_producto` message whose outcome is `executed` or `rejected`
- **THEN** the next CLI message processes as a fresh message (no stale `modificar_producto` clarification prompt)

### Requirement: Real-flow single ProcessedIntent invariant

When driven by the real HTTP endpoint or the interactive CLI driver, the initial orchestrator MUST emit exactly one `ProcessedIntent` per `modificar_producto` message; the system MUST NOT decompose the modification into separate `quitar_producto` and `agregar_producto` outcomes.

#### Scenario: HTTP emits one ProcessedIntent for the modification

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** `process_incoming_message_transactional` returns exactly one `ProcessedIntent` whose `intent == "modificar_producto"`

#### Scenario: CLI emits one ProcessedIntent for the modification

- **WHEN** the interactive CLI driver processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the CLI prints exactly one modification response; no separate `Quité` and `Agregué` responses appear in the printed output for the same modification
