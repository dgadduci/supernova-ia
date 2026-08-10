# Delta for initial-intent-dispatcher

## ADDED Requirements

### Requirement: Explicit iniciar_pedido dispatch is session-safe

When the classifier returns `INICIAR_PEDIDO` and the active session has no pending context, the initial dispatcher SHALL delegate the classified message to the approved new-order transition. It SHALL preserve the existing rejection behavior for all unsupported intents and SHALL NOT invoke the transition for any other intent.

#### Scenario: Explicit new-order intent reaches the transition

- **WHEN** the classifier returns one `ClassifiedIntent(intent=INICIAR_PEDIDO, mensaje="quiero hacer otro pedido")`
- **THEN** the dispatcher calls the new-order transition once with the supplied database session, conversation session, and classified message
- **AND** returns that transition's `ProcessedIntent`

### Requirement: Successful session replacement ends the current turn

After `iniciar_pedido` successfully creates a successor session/order, the dispatcher SHALL NOT dispatch later classified intents from that same inbound message against the closed predecessor session.

#### Scenario: Later product intent is not applied to the closed order

- **WHEN** the classifier returns `iniciar_pedido` followed by `agregar_producto`
- **AND** the new-order transition succeeds
- **THEN** the dispatcher returns only the successor transition result for that boundary
- **AND** it does not call the product orchestrator with the closed predecessor session
