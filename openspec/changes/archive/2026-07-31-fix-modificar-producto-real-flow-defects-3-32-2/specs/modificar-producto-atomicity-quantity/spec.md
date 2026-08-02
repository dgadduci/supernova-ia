## ADDED Requirements

### Requirement: Real-flow atomic-quantity contract

The atomic-quantity contract for `modificar_producto` MUST hold when the user message arrives through the real `POST /comercios/{id}/clientes/{id}/incoming-messages` endpoint or through the interactive CLI driver at `backend/scripts/cli_chat_client.py`, not only through hand-crafted orchestrator fixtures. Both reproduction phrases MUST produce the documented outcomes end-to-end through the real HTTP/CLI entry points.

#### Scenario: HTTP endpoint transfers the full source quantity on omitted quantity

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the source `PedidoProducto` row is removed; a destination `PedidoProducto` row exists with `cantidad == 4`; the rendered response message contains the explicit quantity `4` on both sides; the destination `cantidad` is never `1`

#### Scenario: CLI driver transfers the full source quantity on omitted quantity

- **WHEN** the interactive CLI driver receives `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the source `PedidoProducto` row is removed; the destination `PedidoProducto` row has `cantidad == 4`; the printed order table shows the destination line with `cantidad == 4` and no source line

#### Scenario: HTTP endpoint preserves source when destination is rejected

- **WHEN** `POST /comercios/{id}/clientes/{id}/incoming-messages` receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`; no destination `PedidoProducto` row exists; the rendered response message confirms the Pedido is unchanged; the response orchestrator emits exactly one `CustomerResponse` whose `intent == "modificar_producto"`

#### Scenario: CLI driver preserves source when destination is rejected

- **WHEN** the interactive CLI driver receives `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with `Empanada de Jamón y Queso x5` and `caramelo` is absent from the catalog
- **THEN** the source `PedidoProducto` row remains with `cantidad == 5`; no destination `PedidoProducto` row exists; the printed order table shows the source line unchanged; the printed customer response confirms the Pedido is unchanged

### Requirement: Real-flow regression matrix drives the seam

The system MUST add two test files that drive the real HTTP endpoint and the real CLI driver with both reproduction phrases:

- `backend/tests/test_modificar_producto_real_flow_http.py` — drives `POST /comercios/{id}/clientes/{id}/incoming-messages`.
- `backend/tests/test_modificar_producto_real_flow_cli.py` — drives `backend/scripts/cli_chat_client.py`.

The two test files MUST coexist with the existing 3.32.1 orchestrator-level suites; no existing test file is removed, renamed, or weakened.

#### Scenario: HTTP regression test asserts the rendered outcome

- **WHEN** the new HTTP regression test runs against `supernova_test`
- **THEN** it asserts the rendered `CustomerResponse.message`, the resulting `PedidoProducto` rows, and the `Session.context_type` for both reproduction phrases

#### Scenario: CLI regression test asserts the printed outcome

- **WHEN** the new CLI regression test runs against `supernova_test`
- **THEN** it asserts the printed customer response and the printed order table for both reproduction phrases

#### Scenario: Existing 3.32.1 tests remain green

- **WHEN** the new real-flow regression tests run alongside the existing orchestrator-level suites
- **THEN** every existing 3.32.1 test passes unchanged
