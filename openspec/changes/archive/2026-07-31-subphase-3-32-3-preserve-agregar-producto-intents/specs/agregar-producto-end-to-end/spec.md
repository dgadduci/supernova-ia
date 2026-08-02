## ADDED Requirements

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
