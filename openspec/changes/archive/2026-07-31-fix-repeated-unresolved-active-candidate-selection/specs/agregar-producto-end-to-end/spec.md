## ADDED Requirements

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
