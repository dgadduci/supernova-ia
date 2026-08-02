## ADDED Requirements

### Requirement: Multiple agregar_producto classifications enter one ordered pending lifecycle
The dispatcher SHALL preserve every `agregar_producto` result from the classifier in classifier order. If any addition requires product resolution, the first unresolved addition SHALL be active and all later additions that remain to be processed SHALL be retained in the FIFO pending queue without replacing an earlier active item.

#### Scenario: Two ambiguous additions are both retained
- **WHEN** the classifier returns two `agregar_producto` items and both initial orchestrator calls return `pending_resolution`
- **THEN** the returned results retain classifier order, the first is active, and the second is queued

#### Scenario: Pending then ready addition is retained
- **WHEN** the first classified addition is pending and the second is ready
- **THEN** the pending addition is active and the ready addition is queued for execution after resolution

#### Scenario: Ready then pending addition preserves order
- **WHEN** the first classified addition is ready and the second is pending
- **THEN** both additions remain represented in classifier order and the ready addition executes before the unresolved addition becomes the active clarification target

### Requirement: Non-agregar dispatcher behavior remains unchanged
The batch-preservation behavior SHALL apply only to `agregar_producto`; existing dispatch and rejection behavior for all other intent names SHALL remain unchanged.

#### Scenario: Other intent types are not inserted into product-selection queue
- **WHEN** a classifier result mixes `agregar_producto` with `quitar_producto`, `modificar_producto`, or an unsupported intent
- **THEN** the dispatcher SHALL NOT enqueue those other intents as product-selection work
