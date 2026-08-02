## ADDED Requirements

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
