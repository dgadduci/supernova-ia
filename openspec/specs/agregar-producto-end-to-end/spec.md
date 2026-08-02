# Capability: agregar-producto-end-to-end

## Purpose

Define the end-to-end integration test that proves the `agregar_producto` lifecycle (initial pending context → unique reply → executed order line, plus an additional ambiguous reply) against real components and the `supernova_test` database, with minimal fixtures and no mocks on the main flow.

## Requirements

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

### Requirement: Multi-product pending-resolution regression coverage
The integration suite SHALL prove that every `agregar_producto` classified from one customer message is preserved and executed exactly once across pending product-selection resolution using real application components and the test database.

#### Scenario: Pending addition followed by ready addition
- **WHEN** one message classifies an ambiguous addition followed by an exact addition and the customer resolves the ambiguity
- **THEN** both order lines are created exactly once in classifier order, both executed outcomes are returned, and pending context is cleared

#### Scenario: Two pending additions require two replies
- **WHEN** one message produces two ambiguous additions
- **THEN** the first reply executes the first addition and promotes the second as active, the second reply executes the second addition, and neither intent is lost or duplicated

#### Scenario: Repeated ambiguity preserves all additions
- **WHEN** the reply for the active addition remains ambiguous
- **THEN** no order line is created, the same addition remains active, and all queued additions remain in their original order

#### Scenario: Consecutive ready additions drain after resolution
- **WHEN** resolving the active addition exposes multiple queued ready additions
- **THEN** all additions execute in FIFO order within the same outer transaction and one customer response can be produced for each outcome

### Requirement: Existing single-product behavior remains valid
The existing single pending `agregar_producto` happy path and ambiguous-reply behavior SHALL continue to pass unchanged.

#### Scenario: Single pending addition regression
- **WHEN** the existing two-message product-selection flow runs
- **THEN** it creates the same single order line and clears context under the same conditions as before

### Requirement: Exact HTTP sequential ambiguous-addition regression
The PostgreSQL-backed integration suite SHALL exercise the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` pipeline with the messages `quiero una empanada de carne y una pizza de muzarela`, `picante`, and `grande`. It SHALL mock only the external LLM boundary when needed and SHALL NOT mock queue, promotion, resolver, handler, transaction, or response orchestration.

#### Scenario: First turn shows only Carne clarification
- **WHEN** the initial HTTP message produces ambiguous Carne followed by ambiguous Pizza
- **THEN** the response contains exactly one clarification for Carne, Carne is active, Pizza is the sole queue item, context is `product_selection`, no handler has run, and no order row exists

#### Scenario: Second turn executes Carne and promotes Pizza
- **WHEN** the customer replies `picante`
- **THEN** the response contains the Carne Picante execution confirmation first and the Pizza clarification second, Pizza is active, the queue is empty, and exactly one Carne Picante order row exists

#### Scenario: Third turn executes Pizza and clears state
- **WHEN** the customer then replies `grande`
- **THEN** Pizza Grande executes exactly once, pending active and queue are empty, context is cleared, and the final order contains Carne Picante quantity 1 and Pizza Grande quantity 1

### Requirement: Queue permutations preserve processing order
Integration coverage SHALL include three ambiguous additions, ready-before-pending, pending-before-ready, and pending-ready-pending classifications. Only the current active clarification SHALL be exposed, and promoted ready additions SHALL execute automatically in source order.

#### Scenario: Three ambiguous products advance one at a time
- **WHEN** one message produces three ambiguous additions
- **THEN** only the first clarification appears initially, the second appears after the first executes, the third appears after the second executes, and all three execute exactly once

#### Scenario: Pending ready pending advances correctly
- **WHEN** source order is pending A, ready B, pending C
- **THEN** A is initially active with B and C queued; after A resolves, B executes and C clarification is returned after A and B outcomes

### Requirement: Queue preserves quantity and candidate scope
End-to-end coverage SHALL prove that every queued intent retains its original quantity and candidate IDs across requests and SHALL NOT broaden candidate lookup beyond the persisted candidate set merely because the intent was promoted.

#### Scenario: Distinct quantities survive two selections
- **WHEN** the message is `quiero 4 empanadas de carne y 2 pizzas de muzarela` and both additions require selection
- **THEN** the selected Carne is added with quantity 4 and the selected Pizza with quantity 2

#### Scenario: Promoted candidate set remains restricted
- **WHEN** a queued ambiguous addition is promoted after an earlier item executes
- **THEN** its candidate IDs equal the persisted queue entry until the active resolver narrows them

### Requirement: Queue lifecycle is lossless and exactly-once
Automated tests SHALL assert active intent, ordered queue contents, context type, response count/order, handler-call count, and persisted order rows after every turn. No queued addition SHALL be lost, executed twice, clarified while inactive, or rebuilt through classification.

#### Scenario: Every handler runs exactly once
- **WHEN** a multi-addition sequence completes successfully
- **THEN** each selected or ready addition's handler was called exactly once and every expected order line exists exactly once

#### Scenario: Queue persists across requests
- **WHEN** the first request creates active plus queued work and the second promotes the queue head
- **THEN** the promoted intent remains available as active for the third request with its original persisted data

### Requirement: Rejection and technical failure preserve lifecycle guarantees
A definitive active rejection SHALL produce its response and continue promotion without discarding the queue. A raised technical exception SHALL roll back all order and pending-state changes from that HTTP turn.

#### Scenario: Rejected active promotes next addition
- **WHEN** the active addition resolves to definitive `rejected` while another addition is queued
- **THEN** the rejection is returned before the next active clarification and the queued addition remains processable

#### Scenario: Later promoted handler exception rolls back
- **WHEN** one addition succeeds in memory and a later promoted handler raises in the same HTTP request
- **THEN** no partial order mutation or queue advancement from that request is committed

### Requirement: Existing intent and quantity-response regressions remain valid
The existing single ambiguous `agregar_producto`, several fully resolved additions, `cantidad_agregada` versus `cantidad_final` response behavior, `quitar_producto`, and `modificar_producto` flows SHALL remain unchanged.

#### Scenario: Single ambiguous addition regression
- **WHEN** the established one-product clarification flow runs
- **THEN** it produces the same clarification, execution, persistence, and cleanup behavior as before

#### Scenario: Fully resolved additions need no queue
- **WHEN** one message contains several ready additions
- **THEN** all execute in source order and no pending state remains

#### Scenario: Other mutation intents are unaffected
- **WHEN** existing `quitar_producto` and `modificar_producto` regression suites run
- **THEN** their active-context, handler, response, and transaction behavior remains unchanged

### Requirement: Exact CLI acceptance mirrors the HTTP lifecycle
The existing CLI SHALL be exercised with the same three messages and SHALL display only the active clarification on turn one, the Carne confirmation followed by Pizza clarification on turn two, and the Pizza confirmation plus final order table on turn three.

#### Scenario: CLI final order contains both selected products
- **WHEN** the exact three-turn CLI sequence completes
- **THEN** the final table contains Carne Picante quantity 1 and Pizza Grande quantity 1, no product request was lost or duplicated, and CLI cleanup behavior is unchanged

### Requirement: Exact repeated-clarification HTTP regression is covered
The PostgreSQL-backed integration suite SHALL exercise the real incoming-message HTTP endpoint with `quiero una empanada de carne y una pizza`, followed by `picante`, while mocking only the external LLM boundary when necessary. The test SHALL use real recognition, active resolution, pending dispatch, queue promotion, handlers, response orchestration, and transaction processing.

#### Scenario: First turn stores Carne active and Pizza queued
- **WHEN** the exact initial message is posted
- **THEN** the response contains exactly one Carne clarification, Carne is active, Pizza is the sole queue item, both candidate sets and quantities are persisted, and no order row exists

#### Scenario: Second turn does not repeat Carne clarification
- **WHEN** `picante` is posted once
- **THEN** Carne Picante quantity 1 executes exactly once, Pizza is promoted, the response contains the Carne confirmation first and one Pizza clarification second, and the old Carne clarification is absent

### Requirement: Exact three-turn flow completes the promoted queue
The integration suite SHALL submit a third reply that uniquely selects one persisted Pizza candidate, such as `muzzarella grande`, and SHALL verify final pending and order persistence.

#### Scenario: Third turn executes Pizza and clears context
- **WHEN** the promoted Pizza is uniquely selected on the third HTTP turn
- **THEN** Pizza executes exactly once, active and queue are empty, context is null, and the final order contains Carne Picante and the selected Pizza with quantity 1 each

### Requirement: Diagnostic coverage identifies the first failing boundary
Before runtime implementation changes, the exact reproduction SHALL capture classified intent order; active and queued `ProcessedIntent` values; candidate IDs; context type; pending state before and after each turn; restricted candidate catalog; raw `detectar_productos` output; resolver output; status transitions; execution and handler calls; cleanup and promotion; returned responses; and final `PedidoProducto` rows.

#### Scenario: Diagnosis precedes runtime correction
- **WHEN** implementation work begins
- **THEN** the first boundary where `picante` diverges from unique ready resolution is recorded before any runtime file is modified

### Requirement: Quantities, candidate scope, and queue fields remain lossless
The PostgreSQL-backed regression suite SHALL prove that active and queued quantities and candidate IDs survive across turns and that promotion reuses the persisted queue value without unrestricted recognition or reconstruction.

#### Scenario: Distinct quantities survive active execution and promotion
- **WHEN** the initial message is `quiero 4 empanadas de carne y 2 pizzas` and the customer replies `picante`
- **THEN** Carne Picante quantity 4 is added and promoted Pizza remains pending with quantity 2 and its original candidate IDs

#### Scenario: Candidate outside active scope cannot resolve
- **WHEN** recognition reports a product-presentation ID outside active candidate IDs
- **THEN** no active mutation or handler execution occurs and the queue remains intact

#### Scenario: Promoted Pizza retains complete queued intent
- **WHEN** Carne completes and Pizza is promoted
- **THEN** Pizza retains its source text, quantity, resolved data, requirements, candidate IDs, status, recognizer, handler, and intent name

### Requirement: Queue lifecycle failures and regressions remain covered
Automated tests SHALL cover duplicate-active prevention, clarification-only classifier bypass, definitive rejection promotion, technical rollback, one ambiguous product, multiple ambiguous products, multiple ready products, response quantity semantics, and unchanged quitar/modificar behavior.

#### Scenario: No duplicate active intent remains
- **WHEN** `picante` resolves and executes Carne
- **THEN** no Carne copy remains active or queued and its handler and response occur exactly once

#### Scenario: Definitive rejection advances queue
- **WHEN** the active handler returns `rejected`
- **THEN** Pizza is promoted and clarified without leaving the rejected item active

#### Scenario: Technical exception rolls back HTTP turn
- **WHEN** active execution or later queue advancement raises
- **THEN** no partial order row or pending-state advancement from that request is committed

#### Scenario: Existing mutation flows remain unchanged
- **WHEN** established single ambiguous, multiple ready, sequential ambiguous, `cantidad_agregada`, `quitar_producto`, and `modificar_producto` regressions run
- **THEN** they continue to pass with their existing response, persistence, ordering, and transaction behavior

### Requirement: Manual CLI acceptance mirrors the corrected lifecycle
The existing CLI SHALL run the same three-turn sequence from a fresh session and display only the active clarification on turn one, the Carne confirmation followed by Pizza clarification on turn two, and the Pizza confirmation plus final order on turn three.

#### Scenario: CLI no longer loops on picante
- **WHEN** the operator enters the initial message and then `picante`
- **THEN** Carne Picante is added once, Pizza candidates are displayed immediately, and the Carne clarification is not repeated

#### Scenario: CLI final order is complete
- **WHEN** the operator selects one promoted Pizza candidate
- **THEN** pending context and queue clear, the order table contains both selected products with preserved quantities, and session cleanup remains unchanged