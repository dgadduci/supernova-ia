## ADDED Requirements

### Requirement: Active completion removes only the authoritative active value
After a ready active `agregar_producto` intent executes or is definitively rejected, pending execution SHALL remove only that completed active item from the authoritative pending state. It SHALL NOT restore a stale pre-resolution active value, discard the queue, or duplicate an active item.

#### Scenario: Executed Carne is removed exactly once
- **WHEN** resolved Carne executes while Pizza is queued
- **THEN** Carne appears in outcomes exactly once, no Carne copy remains active or queued, and Pizza remains available for promotion

#### Scenario: Technical exception preserves rollback ownership
- **WHEN** active or promoted execution raises an exception
- **THEN** the exception propagates, pending execution performs no commit or rollback, and the outer transaction can roll back order and pending-state changes

### Requirement: Next queued ambiguous product is promoted losslessly
After a definitive active outcome, pending execution SHALL promote the persisted FIFO queue head using its stored `ProcessedIntent` fields, derive its context type through the existing context-type resolver, make it active, and return exactly one clarification when it remains `pending_resolution`.

#### Scenario: Pizza promotion preserves persisted data
- **WHEN** Carne executes and queued Pizza stores quantity, candidate IDs, source text, resolved data, requirements, recognizer, and handler
- **THEN** promoted Pizza preserves those values, becomes active with `product_selection` context, and is returned once after the Carne outcome

#### Scenario: Rejected active still promotes Pizza
- **WHEN** the active addition receives a definitive rejected handler result and Pizza is queued
- **THEN** the rejection is returned first, Pizza is promoted and clarified second, and the session is not left on the rejected active item

### Requirement: Queue advancement remains deterministic and exactly once
Pending execution SHALL execute consecutive promoted ready additions in FIFO order and SHALL stop at queue exhaustion, a promoted `pending_resolution` intent, or a `failed` result. Each outcome and handler invocation SHALL occur exactly once.

#### Scenario: Pending ready pending sequence remains ordered
- **WHEN** resolving active A exposes ready B followed by ambiguous C
- **THEN** outcomes are A definitive, B definitive, and C pending in FIFO order, with C active and no duplicate outcomes

#### Scenario: Final promoted selection clears pending state
- **WHEN** the customer resolves the last promoted Pizza candidate and its handler executes
- **THEN** active and queue are empty, context is cleared, and both selected order lines exist exactly once
