## MODIFIED Requirements

### Requirement: Status replies preserve conversation and commerce isolation

The status-query branch SHALL not write pending intents, alter
`session.context_type`, repeat an intent, inspect product candidate sets, or
widen any selection scope. When no pending context is active, the authoritative
initial classifier dispatches the status query normally. When a supported
pending context is active and a closed deterministic status predicate matches,
the pending dispatcher MAY invoke this existing read-only branch directly;
that interruption SHALL preserve the pending state exactly.

#### Scenario: Explicit status request during pending context is read-only

- **WHEN** a product-selection or order-line-selection context is active and
  the customer sends an explicit status question
- **THEN** `consultar_estado_pedido` is dispatched without an LLM call
- **AND** the response concerns only `session.id_pedido`
- **AND** existing candidate IDs, queue, pending state and context type remain
  unchanged

#### Scenario: Non-status pending reply retains resolver priority

- **WHEN** a supported pending context is active and the customer sends a
  product clarification such as `Grande`
- **THEN** the message is handled only by that active context
- **AND** `consultar_estado_pedido` is not dispatched in the same turn
