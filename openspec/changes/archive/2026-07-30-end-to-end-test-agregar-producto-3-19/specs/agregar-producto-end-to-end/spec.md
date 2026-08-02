## ADDED Requirements

### Requirement: End-to-end agregar_producto integration test
The test suite SHALL include an integration test that creates the commerce, client, session, draft pedido, product with two presentations (`chica` and `grande`), and prices; calls `process_initial_agregar_producto` with `quiero 2 pizzas de mozzarella`; and asserts `status == "pending_resolution"`, `session.context_type == "product_selection"`, an active pending intent exists, and no `PedidoProducto` was created.

#### Scenario: Initial message becomes pending context
- **WHEN** `process_initial_agregar_producto(db, session, "quiero 2 pizzas de mozzarella")` is invoked against a freshly seeded commerce
- **THEN** the result is `pending_resolution`, `session.context_type` is `product_selection`, the active pending intent is populated, and no `PedidoProducto` row exists

### Requirement: Ready execution completes the lifecycle
The integration test SHALL call `dispatch_pending_context(db, session, "la grande")` and assert `status == "executed"`, exactly one `PedidoProducto` row for the `grande` presentation with `cantidad == 2`, `precio_unitario` matching the database price, an empty `session.pending_intents`, and `session.context_type is None`.

#### Scenario: Unique reply produces executed order line
- **WHEN** `dispatch_pending_context(db, session, "la grande")` is invoked after the initial pending context
- **THEN** the result is `executed`, exactly one `PedidoProducto` exists with the grande presentation, quantity 2, and the database price; pending intents and context type are cleared

### Requirement: Ambiguous reply preserves context
The integration test SHALL also cover a second ambiguous reply that keeps `status == "pending_resolution"`, preserves `session.context_type`, and creates no new `PedidoProducto` rows.

#### Scenario: Ambiguous reply keeps pending context
- **WHEN** an additional ambiguous reply is dispatched while the context is still pending
- **THEN** the result is `pending_resolution`, context type and pending intent remain, and no `PedidoProducto` row is created

### Requirement: Real component integration
The integration test SHALL use real services against `supernova_test` and SHALL NOT mock the recognizer, resolver, processor, dispatcher, handler, or services for the main flow.

#### Scenario: Tests use real services only
- **WHEN** the integration test runs
- **THEN** it inserts data through existing models and calls real application services without mocking the main flow

### Requirement: Minimal fixtures and reporting
The integration test SHALL use minimal fixtures and SHALL run only against `supernova_test`, reporting the test result.

#### Scenario: Single integration test reporting
- **WHEN** the integration test runs against `supernova_test`
- **THEN** it reports the relevant test result without adding unrelated tests or refactors
