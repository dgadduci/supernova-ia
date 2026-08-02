## ADDED Requirements

### Requirement: Real-flow handler re-read invariant

When the resolved `ProcessedIntent` originates from the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or from the interactive CLI driver, `execute_modificar_producto` SHALL re-read the current `PedidoProducto.cantidad` for the resolved source line inside the same transaction boundary, SHALL pass the re-read value to `PedidoProductoService.modify_product` as the explicit transfer quantity, and SHALL NOT substitute `1`. The re-read MUST hold for both the exact reproduction phrases (`cambia las empanadas de verdura por empanadas carne picante` and `cambia las 5 empanadas de jamon y queso por un caramelo`), not only for hand-crafted `ProcessedIntent` fixtures.

#### Scenario: Real HTTP endpoint drives the omitted-quantity re-read

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** `execute_modificar_producto` re-reads `cantidad == 4`, passes `4` to `PedidoProductoService.modify_product`, and the destination `PedidoProducto` row has `cantidad == 4`; the destination `cantidad` is never `1`

#### Scenario: Real CLI driver drives the omitted-quantity re-read

- **WHEN** the interactive CLI driver at `backend/scripts/cli_chat_client.py` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the orchestrator builds the `ready` `ProcessedIntent` with `cantidad is None`, `execute_modificar_producto` re-reads `cantidad == 4`, passes `4` to the service, and the destination row has `cantidad == 4`

#### Scenario: Real pipeline does not substitute one for omitted quantity

- **WHEN** the real HTTP endpoint or the interactive CLI driver delivers a `modificar_producto` message with `cantidad is None`
- **THEN** the captured per-layer trace records `cantidad == 4` (the re-read source quantity) as the value passed to `PedidoProductoService.modify_product`; the trace never records `cantidad == 1` for an omitted-quantity message

### Requirement: Real-flow single ProcessedIntent invariant

When driven by the real HTTP endpoint or the interactive CLI driver, `execute_modificar_producto` SHALL return exactly one `ProcessedIntent` per modification message; the pipeline SHALL NOT produce a `quitar_producto` followed by an `agregar_producto` outcome for a single `modificar_producto` message.

#### Scenario: HTTP single ProcessedIntent invariant

- **WHEN** the real HTTP endpoint processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** `process_incoming_message_transactional` returns exactly one `ProcessedIntent` whose `intent == "modificar_producto"`; no `agregar_producto` and no `quitar_producto` outcome is emitted for the same message

#### Scenario: CLI single ProcessedIntent invariant

- **WHEN** the interactive CLI driver processes any `modificar_producto` message (including the exact reproduction phrases)
- **THEN** the CLI prints exactly one modification response; the printed output never contains both a `Quité` message and an `Agregué` message for the same modification

### Requirement: Real-flow validation-before-mutation invariant

When driven by the real HTTP endpoint or the interactive CLI driver, every destination validation MUST complete before any source mutation; no commit or flush SHALL occur between source removal and destination addition; the source `PedidoProducto` row SHALL remain unchanged when the destination is rejected.

#### Scenario: HTTP preserves source when destination is rejected

- **WHEN** the real HTTP endpoint receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`, no destination `PedidoProducto` row exists, and the rendered response message confirms the Pedido is unchanged

#### Scenario: CLI preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the printed order table shows the source line unchanged with `cantidad == 5`, no destination line appears, and the printed customer response confirms the Pedido is unchanged
