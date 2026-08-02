# Capability: quitar-producto-end-to-end
## ADDED Requirements

### Requirement: End-to-end quitar_producto integration test
The test suite SHALL include an integration test that creates the commerce, client, session, draft pedido, product with two presentations (`chica` and `grande`), and prices; calls `process_initial_quitar_producto` with `quitá una pizza`; and asserts `status == "pending_resolution"`, `session.context_type == "order_line_selection"`, an active pending intent exists, and no `PedidoProducto` was deleted.

#### Scenario: Initial message becomes pending context
- **WHEN** `process_initial_quitar_producto(db, session, "quitá una pizza")` is invoked against a freshly seeded draft pedido with three `Pizza` lines
- **THEN** the result is `pending_resolution`, `session.context_type` is `order_line_selection`, the active pending intent is populated, and no `PedidoProducto` row is deleted

### Requirement: Refinement narrows candidates
The integration test SHALL call `dispatch_pending_context(db, session, "la grande")` after the initial pending context and assert the active intent's `candidate_ids` is reduced to the two large pizzas and `status == "pending_resolution"`.

#### Scenario: Single refinement narrows candidates
- **WHEN** `dispatch_pending_context(db, session, "la grande")` is invoked after the initial pending context
- **THEN** the active intent has `status == "pending_resolution"`, `candidate_ids` is the two large-pizza `pedido_producto_id` values, and no `PedidoProducto` row is deleted

### Requirement: Unique ready deletes the line and clears context
The integration test SHALL call `dispatch_pending_context(db, session, "la de muzzarella")` after the refinement and assert `status == "executed"`, exactly one `PedidoProducto` row was removed, the remaining lines are unchanged, `session.pending_intents` is empty, and `session.context_type is None`.

#### Scenario: Unique reply produces executed removal
- **WHEN** `dispatch_pending_context(db, session, "la de muzzarella")` is invoked after the refinement
- **THEN** the result is `executed`, the matching `PedidoProducto` row is removed, the other lines are unchanged, `session.pending_intents` is empty, and `session.context_type is None`

### Requirement: Decrement variant
The integration test SHALL cover `quitá 2 empanadas de carne` against a draft pedido with three empanadas and assert `status == "executed"`, the line now has `cantidad == 1`, other lines are unchanged, and pending context is cleared.

#### Scenario: Partial removal decrements the line
- **WHEN** the initial `quitar_producto` intent is `quitá 2 empanadas de carne` against a draft with three empanadas
- **THEN** the result is `executed`, the persisted line has `cantidad == 1`, and other lines are unchanged

### Requirement: Excess quantity variant
The integration test SHALL cover `quitá 4 empanadas` against a draft pedido with two empanadas and assert `status == "rejected"`, the line quantity remains 2, no `PedidoProducto` was deleted, `session.pending_intents` is empty, and `session.context_type is None`.

#### Scenario: Excess quantity is rejected without mutation
- **WHEN** the initial `quitar_producto` intent is `quitá 4 empanadas` against a draft with two empanadas
- **THEN** the result is `rejected`, the persisted line still has `cantidad == 2`, no row is deleted, and the pending context is cleared

### Requirement: Absent product variant
The integration test SHALL cover `quitá la pizza napolitana grande` against a draft pedido whose napolitana grande line is absent and assert `status == "rejected"`, no mutation, and a customer response whose message equals `Ese producto no está en tu pedido.`.

#### Scenario: Absent product is rejected without mutation
- **WHEN** the intent targets a product not in the draft pedido
- **THEN** the result is `rejected`, no row is deleted, and the customer response message is exactly `Ese producto no está en tu pedido.`

### Requirement: Real component integration
The integration test SHALL use real services against `supernova_test` and SHALL NOT mock the recognizer, resolver, processor, dispatcher, handler, response builder, or services for the main flow.

#### Scenario: Tests use real services only
- **WHEN** the integration test runs
- **THEN** it inserts data through existing models and calls real application services without mocking the main flow

### Requirement: Minimal fixtures and reporting
The integration test SHALL use minimal fixtures and SHALL run only against `supernova_test`, reporting the test result.

#### Scenario: Single integration test reporting
- **WHEN** the integration test runs against `supernova_test`
- **THEN** it reports the relevant test result without adding unrelated tests or refactors

### Requirement: agregar_producto regression
The integration test suite SHALL re-run the existing `agregar_producto` end-to-end scenarios (initial pending context → refinement → unique ready → executed) unchanged and SHALL confirm they pass against `supernova_test` to prove the new `ORDER_LINE_SELECTION` context type does not corrupt `PRODUCT_SELECTION`.

#### Scenario: agregar_producto regression passes
- **WHEN** the existing agregar_producto integration tests run against `supernova_test` after the new code lands
- **THEN** they pass unchanged

### Requirement: Consecutive operations
The integration test SHALL cover a flow that adds several products, removes part of one line, removes another complete line, and adds another product through the modern pipeline, asserting the same active session and draft pedido remain coherent and the final quantities match expectations.

#### Scenario: Mixed operations remain coherent
- **WHEN** the same active session is used for `agregar_producto`, `quitar_producto` (partial), `quitar_producto` (complete), and a final `agregar_producto`
- **THEN** the final `PedidoProducto` rows and quantities match the expected state, the session remains coherent, and no stale pending context is left
