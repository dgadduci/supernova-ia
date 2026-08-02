## ADDED Requirements

### Requirement: Initial agregar_producto results stop at the active interaction boundary
When one classification contains multiple `agregar_producto` items, the dispatcher SHALL process them in classifier/source order. It SHALL return immediate outcomes only through the first `pending_resolution` item and SHALL NOT return later queued additions as customer-visible outcomes on that turn.

#### Scenario: Two ambiguous additions expose only the first clarification
- **WHEN** one message produces pending additions for Carne and then Pizza
- **THEN** Carne is active, Pizza is queued, and the returned list contains only the Carne `pending_resolution` result

#### Scenario: Ready before pending executes before clarification
- **WHEN** classified additions are ready A followed by pending B
- **THEN** A executes, B becomes active, and the returned results are A `executed` followed by B `pending_resolution`

#### Scenario: Pending before ready pauses interaction
- **WHEN** classified additions are pending A followed by ready B
- **THEN** A becomes active, B is queued, and the returned list contains only A `pending_resolution`

### Requirement: Initial queue preserves all work after the first unresolved addition
After the first pending `agregar_producto` becomes active, the dispatcher SHALL retain every later `agregar_producto` as its complete persisted `ProcessedIntent` in FIFO source order, whether its current status is `ready` or `pending_resolution`.

#### Scenario: Pending ready pending order is persisted
- **WHEN** classified additions are pending A, ready B, and pending C
- **THEN** A is active and the queue contains B then C with their original statuses and values

#### Scenario: Queued intent data is unchanged
- **WHEN** an ambiguous queued addition has source text, quantity, candidate IDs, resolved data, requirements, handler, intent name, and refinement state
- **THEN** all those values are persisted unchanged and are not reconstructed from customer-facing text

### Requirement: Initial queue behavior remains agregar_producto-specific
The dispatcher SHALL NOT place unrelated `quitar_producto`, `modificar_producto`, or unsupported intents into the `product_selection` queue as part of this sequential-addition behavior.

#### Scenario: Other intents are not inserted behind an addition
- **WHEN** classification contains an `agregar_producto` pending item followed by another intent type
- **THEN** the other intent is not persisted as `product_selection` queue work
