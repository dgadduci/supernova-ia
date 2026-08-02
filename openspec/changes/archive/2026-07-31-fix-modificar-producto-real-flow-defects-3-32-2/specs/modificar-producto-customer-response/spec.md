## ADDED Requirements

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
